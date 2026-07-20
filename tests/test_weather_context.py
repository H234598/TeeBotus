from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import time
from unittest.mock import patch

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.weather_context import (
    _city_id_token,
    extract_residence_city,
    fetch_weather_summary,
    update_city_and_weather_context,
    weather_context_text,
)


def store(tmp_path) -> AccountStore:
    return AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"w" * 32))


def event(identity: str, text: str) -> IncomingEvent:
    return IncomingEvent(
        event_id="signal:1",
        instance="Depressionsbot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key=identity,
        chat_id="+491",
        chat_type="private",
        sender_id=identity,
        sender_name="Signal User",
        text=text,
        message_ref="1",
    )


def prepare_account(account_store: AccountStore) -> tuple[str, str]:
    identity = signal_identity_key(source_uuid="signal-user")
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
    return identity, account_id


def test_extract_residence_city_from_common_german_phrases() -> None:
    assert extract_residence_city("Ich wohne in Berlin und bin heute muede.") == "Berlin"
    assert extract_residence_city("Ich lebe jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne eigentlich in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe eigentlich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist München.") == "München"
    assert extract_residence_city("Ich wohne in Hamburg zur Miete.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Hamburg zur Untermiete.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Hamburg zur Zwischenmiete.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Hamburg nur vorübergehend.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Januar in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe seit März 2025 bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit dem 1. Januar in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit dem 01.01.2025 in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe seit dem 1.1.2025 in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit dem 1.1. in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne seit Anfang Januar in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit letztem Januar in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit dem Sommer in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Weihnachten in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Anfang 2024 in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit dem Einzug in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Beginn meines Studiums in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit dem ersten Tag in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit 2020 zuhause in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne bereits seit fünf Jahren in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Beginn meiner Ausbildung in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne seit Ende meiner Ausbildung in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit Abschluss meiner Ausbildung in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit dem Abschluss meines Studiums in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne seit dem Beginn meiner Lehre in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne seit meiner Ausbildung in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne seit dem letzten Umzug in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit meinem vergangenen Umzug in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne seit ich in Hamburg arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohne aktuell in Hamburg, seit Januar in Berlin.") == "Berlin"
    assert extract_residence_city("Ab Januar wohne ich in Hamburg.") == ""
    assert extract_residence_city("Ab dem 1. Januar bin ich in Hamburg wohnhaft.") == ""
    assert extract_residence_city("Ab dem 01.01.2027 wohne ich in Berlin.") == ""
    assert extract_residence_city("Ab 01.01.2027 lebe ich in Potsdam.") == ""
    assert extract_residence_city("Am 01.01.2027 ist mein Wohnort Hamburg.") == ""
    assert extract_residence_city("Ab dem Sommer ist mein Wohnort Hamburg.") == ""
    assert extract_residence_city("Ich wohne wegen der Arbeit in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe aufgrund meines Studiums bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne aus beruflichen Gründen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Berlin, wohne aber beruflich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne dienstlich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe aus familiären Gründen bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich arbeite aus beruflichen Gründen in Hamburg.") == ""
    assert extract_residence_city("Ich arbeite wegen der Arbeit in Hamburg.") == ""
    assert extract_residence_city("Hamburg ist der Ort, in dem ich lebe.") == "Hamburg"
    assert extract_residence_city("Der Ort, in dem ich lebe, ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Weißt du, wo ich wohne? In Köln.") == "Köln"
    assert extract_residence_city("Berlin ist der Ort, in dem ich wohne.") == "Berlin"
    assert extract_residence_city("Der Ort, in dem ich wohne, ist Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg ist der Ort, in dem ich arbeite.") == ""
    assert extract_residence_city("Ich wohne an einem Ort namens Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir leben an einem Ort namens Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich arbeite an einem Ort namens Hamburg.") == ""
    assert extract_residence_city("Ich wohne dort, wo ich arbeite: in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Hansestadt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in der Hansestadt Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Hamburgs Norden.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Berlins Westen.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Hafenstadt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Universitätsstadt Heidelberg.") == "Heidelberg"
    assert extract_residence_city("Ich wohne in der Kreisstadt Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in der Landeshauptstadt München.") == "München"
    assert extract_residence_city("Ich wohne in Hamburg, dem Ort, den ich Zuhause nenne.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Köln, genauer: Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne in Berlin, meine Wohnadresse ist Potsdam.") == ""
    assert extract_residence_city("Ich wohne sowohl in Berlin als auch in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber auch in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber auch meine Frau in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und arbeite auch in Hamburg.") == "Berlin"
    assert extract_residence_city("Meine Adresse ist Hamburg, mein Wohnort Berlin.") == ""
    assert extract_residence_city("Meine frühere Adresse war Köln, meine aktuelle ist Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne teilweise in Hamburg und teilweise in Berlin.") == ""
    assert extract_residence_city("Hamburg war mein Wohnort, heute ist es Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg war mein Wohnort, heute bin ich in Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg war mein Wohnort, heute lebe ich in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg, beziehungsweise Berlin.") == ""
    assert extract_residence_city("Ich wohne entweder in Hamburg oder Berlin.") == ""
    assert extract_residence_city("Ich wohne weder in Hamburg noch in Berlin.") == ""
    assert extract_residence_city("Am 1. Januar ist mein Wohnort Hamburg.") == ""
    assert extract_residence_city("Am 1. Mai bin ich in Hamburg wohnhaft.") == ""
    assert extract_residence_city("Im Januar wohne ich in Hamburg.") == ""
    assert extract_residence_city("Im Sommer bin ich in Hamburg wohnhaft.") == ""
    assert extract_residence_city("Zu Weihnachten wohne ich in Hamburg.") == ""
    assert extract_residence_city("Ich komme aus Hamburg, aber bin unterwegs.") == ""


def test_extract_residence_city_from_inverted_and_colloquial_forms() -> None:
    assert extract_residence_city("Wohnhaft bin ich in Berlin.") == "Berlin"
    assert extract_residence_city("Ansässig sind wir bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein aktueller Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin bleibt mein Wohnort.") == "Berlin"
    assert extract_residence_city("Hamburg bleibt mein Zuhause.") == "Hamburg"
    assert extract_residence_city("München bleibt mein Lebensmittelpunkt.") == "München"
    assert extract_residence_city("Ich hab meinen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich hab' meinen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Berlin ist nicht mehr mein Wohnort, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mehr mein Wohnort, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Nicht Berlin, sondern Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, ich lebe in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ehemals ansässig sind wir bei Hamburg.") == ""


def test_extract_residence_city_rejects_future_residence() -> None:
    assert extract_residence_city("Ab nächstem Jahr wohne ich in Hamburg.") == ""
    assert extract_residence_city("Ab nächstem Jahr lebe ich in Hamburg.") == ""
    assert extract_residence_city("Bald wohne ich in Hamburg.") == ""
    assert extract_residence_city("Mein künftiger Wohnort ist Hamburg.") == ""
    assert extract_residence_city("Mein zukünftiger Wohnsitz liegt in Hamburg.") == ""
    assert extract_residence_city("Nächstes Jahr ist mein Wohnort Hamburg.") == ""
    assert extract_residence_city("Ich wohne derzeit in Berlin, nächstes Jahr in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ziehe morgen nach Hamburg.") == "Berlin"


def test_extract_residence_city_from_additional_change_forms() -> None:
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, bin jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich stamme aus Berlin, lebe jetzt aber in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich stamme aus Berlin, wohne heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich stamme aus Berlin, lebe aber inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich komme aus Berlin und wohne dort.") == "Berlin"
    assert extract_residence_city("Ich stamme aus Potsdam und lebe dort.") == "Potsdam"
    assert extract_residence_city("Ich komme aus Berlin, wohne aber dort.") == "Berlin"
    assert extract_residence_city("Ich komme aus Berlin und bin dort wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich stamme aus Potsdam und bin dort ansässig.") == "Potsdam"
    assert extract_residence_city("Ich komme aus Berlin und arbeite dort.") == ""
    assert extract_residence_city("Ich arbeite in Berlin, wo ich wohne.") == "Berlin"
    assert extract_residence_city("Ich studiere in Hamburg, wo ich lebe.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin, dort wohne ich.") == "Berlin"
    assert extract_residence_city("Ich studiere in Hamburg, da lebe ich.") == "Hamburg"
    assert extract_residence_city("Ich wohne dort, wo ich studiere: in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe da, wo ich lerne: in Dresden.") == "Dresden"
    assert extract_residence_city("Hamburg, daheim bin ich.") == "Hamburg"
    assert extract_residence_city("Potsdam, dort bin ich zuhause.") == "Potsdam"
    assert extract_residence_city("Berlin, dort lebe ich.") == "Berlin"
    assert extract_residence_city("Berlin, dort arbeite ich.") == ""
    assert extract_residence_city("Ich habe in Hamburg meinen Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Ich habe in Potsdam meine Bleibe.") == "Potsdam"
    assert extract_residence_city("Ich hab' in Berlin meine Bleibe.") == "Berlin"
    assert extract_residence_city("Ich stamme aus Berlin, aber arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich lebe nun nicht mehr in Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen aktuell nicht mehr bei Berlin, sondern bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe nun nicht mehr in Berlin, sondern arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wurde in Berlin geboren und lebe heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Geboren wurde ich in Berlin und lebe heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Geboren in Berlin, lebe ich heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe in Berlin gewohnt, bin jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir haben bei Berlin gelebt, sind inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe in Berlin gewohnt, arbeite jetzt in Hamburg.") == ""
    assert extract_residence_city("Ich hab in Berlin gewohnt, jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir haben bei Berlin gelebt, heute Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich hab in Berlin gewohnt, jetzt arbeite in Hamburg.") == ""
    assert extract_residence_city("Berlin war mein Wohnort, ich bin jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin war früher mein Wohnsitz, aber ich bin inzwischen bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Berlin war mein Wohnort, ich arbeite jetzt in Hamburg.") == ""
    assert extract_residence_city("Berlin war mein Wohnort und ich lebe jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin war mein Wohnsitz und ich wohne inzwischen bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Berlin war mein Wohnort und ich arbeite jetzt in Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort hat sich von Berlin nach Hamburg verlagert.") == "Hamburg"
    assert extract_residence_city("Unser Wohnsitz hat sich aus Berlin nach Potsdam verschoben.") == "Potsdam"
    assert extract_residence_city("Mein Arbeitsort hat sich von Berlin nach Hamburg verlagert.") == ""
    assert extract_residence_city("Mein Wohnort verlegte sich von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Unser Wohnsitz verlegte sich aus Berlin nach Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Arbeitsort verlegte sich von Berlin nach Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort ist Hamburg geworden.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Potsdam geworden.") == "Potsdam"
    assert extract_residence_city("Hamburg ist mein neuer Wohnort.") == "Hamburg"
    assert extract_residence_city("Potsdam ist unser neues Zuhause.") == "Potsdam"
    assert extract_residence_city("Hamburg ist mein neuer Arbeitsort.") == ""
    assert extract_residence_city("Hamburg ist jetzt mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Potsdam ist inzwischen unser Zuhause.") == "Potsdam"
    assert extract_residence_city("Hamburg ist jetzt mein Arbeitsort.") == ""
    assert extract_residence_city("Ich bin bei Hamburg beruflich ansässig.") == ""
    assert extract_residence_city("Ich bin bei Potsdam dienstlich wohnhaft.") == ""
    assert extract_residence_city("Ich bin in Hamburg registriert.") == "Hamburg"
    assert extract_residence_city("Wir sind bei Potsdam registriert.") == "Potsdam"
    assert extract_residence_city("Ich bin in Hamburg zur Schule registriert.") == ""
    assert extract_residence_city("Mein Wohnort wurde von Berlin nach Hamburg verschoben.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz wurde nach Potsdam verschoben.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort wird nach Hamburg verschoben.") == ""
    assert extract_residence_city("Mein Wohnort ist nach Hamburg verlegt worden.") == "Hamburg"
    assert extract_residence_city("Unser Wohnsitz ist von Berlin nach Potsdam verschoben worden.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort wird nach Hamburg verlegt.") == ""
    assert extract_residence_city("Ich habe meinen Wohnsitz aus Berlin nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Ich habe den Wohnort aus Berlin nach Potsdam verlegt.") == "Potsdam"
    assert extract_residence_city("Ich wohnte in Berlin, bin aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir lebten bei Berlin, sind inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohnte in Berlin, arbeite aber jetzt in Hamburg.") == ""
    assert extract_residence_city("Ich war in Berlin wohnhaft, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich war in Berlin ansässig, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich war in Berlin gemeldet, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Nach meinem Umzug bin ich nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich lebe derzeit in Deutschland, genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne jetzt in Hamburg statt in Berlin.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Hamburg anstatt in Berlin.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Hamburg anstelle von Berlin.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, sondern ich lebe in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, sondern in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, doch in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, jedoch in Hamburg.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort, aber Hamburg mein Wohnort.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort, aber Hamburg mein Arbeitsort.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Arbeitsort, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, sondern ich arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin; zu Hause bin ich in Potsdam.") == ""


def test_extract_residence_city_from_change_timing_forms() -> None:
    assert extract_residence_city("Früher in Hamburg, jetzt in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin letzten Monat nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich zog nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, wohnen tue ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne mal in Berlin, mal in Hamburg.") == ""
    assert extract_residence_city("Ich wohne teils in Berlin, teils in Hamburg.") == ""
    assert extract_residence_city("Ich lebe abwechselnd in Berlin und Hamburg.") == ""
    assert extract_residence_city("Meine Wohnorte sind Berlin und Hamburg.") == ""
    assert extract_residence_city("Ab morgen wohne ich in Berlin.") == ""


def test_extract_residence_city_from_direction_and_edge_relations() -> None:
    assert extract_residence_city("Ich wohne im Norden von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe im Süden von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Westen von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe im Osten von Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne am Rand von Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnort liegt am Rand von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Norden von Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne am Rand von Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne kurz vor Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt hinter der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne vor Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich fahre vor Berlin vorbei.") == ""


def test_extract_residence_city_handles_settlement_labels() -> None:
    for label in ("Ortschaft", "Gemeinde", "Kommune", "Metropole", "Hauptstadt"):
        assert extract_residence_city(f"Ich wohne in der {label} Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer Ortschaft namens Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer Gemeinde genannt Hamburg.") == "Hamburg"


def test_extract_residence_city_normalizes_city_area_suffixes() -> None:
    for suffix in ("Mitte", "Stadt", "Zentrum", "Innenstadt", "Stadtmitte", "Altstadt"):
        assert extract_residence_city(f"Ich wohne in Berlin-{suffix}.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin Stadt.") == "Berlin"
    assert extract_residence_city("Ich wohne in Baden-Baden.") == "Baden-Baden"
    assert extract_residence_city("Ich wohne in Berlin-Brandenburg.") == "Berlin-Brandenburg"


def test_extract_residence_city_from_genitive_relations() -> None:
    assert extract_residence_city("Ich wohne in der Nähe Berlins.") == "Berlin"
    assert extract_residence_city("Ich lebe unweit Dresdens.") == "Dresden"
    assert extract_residence_city("Mein Wohnort liegt außerhalb Berlins.") == "Berlin"
    assert extract_residence_city("Ich wohne am Rand Dresdens.") == "Dresden"
    assert extract_residence_city("Ich lebe im Umland Potsdams.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Norden Berlins.") == "Berlin"
    assert extract_residence_city("Ich wohne unweit Berlin und Hamburg.") == ""


def test_extract_residence_city_from_short_profile_forms() -> None:
    assert extract_residence_city("Wohnhaft: Berlin.") == "Berlin"
    assert extract_residence_city("Ansässig: Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort = Berlin.") == "Berlin"
    assert extract_residence_city("Wohne: Leipzig.") == "Leipzig"
    assert extract_residence_city("Bin wohnhaft: Berlin.") == "Berlin"
    assert extract_residence_city("Derzeit wohnhaft Berlin.") == "Berlin"
    assert extract_residence_city("Aktuell ansässig Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein aktueller Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Mein jetziger Wohnsitz Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe Berlin.") == "Berlin"
    assert extract_residence_city("Herkunft: Hamburg.") == ""
    assert extract_residence_city("Arbeitsort: Berlin.") == ""


def test_extract_residence_city_from_profile_address_and_study_forms() -> None:
    assert extract_residence_city("In Berlin wohnhaft bin ich.") == "Berlin"
    assert extract_residence_city("Ich wohne im Berliner Stadtteil Prenzlauer Berg.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Berliner Innenstadt.") == "Berlin"
    assert extract_residence_city("Ich wohne am Berliner Stadtrand.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlins Nähe.") == "Berlin"
    assert extract_residence_city("Ich wohne südlich Berlins.") == "Berlin"
    assert extract_residence_city("Ich wohne fünf Kilometer von Berlin entfernt.") == "Berlin"
    assert extract_residence_city("Ich wohne fünf Kilometer außerhalb von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Berliner Umland.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Region Berlin.") == "Berlin"
    assert extract_residence_city("Meine Anschrift: 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Leipzig.") == "Leipzig"
    assert extract_residence_city("Meldeanschrift: Dresden.") == "Dresden"
    assert extract_residence_city("Privatadresse: Bonn.") == "Bonn"
    assert extract_residence_city("Meine Privatanschrift: Köln.") == "Köln"
    assert extract_residence_city("Adresse: Musterstraße 1, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 1, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meine aktuelle Wohnadresse lautet Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne während meines Studiums in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne nach dem Studium in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne während der Ausbildung in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne nach der Lehre in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nach meinem Umzug in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne für zwei Wochen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne für drei Monate in Rostock.") == "Rostock"
    assert extract_residence_city("Ich lebe für zwei Jahre bei Kiel.") == "Kiel"
    assert extract_residence_city("Ich wohne für drei Tage in Mainz.") == "Mainz"
    assert extract_residence_city("Ich lebe für ein Jahr bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne langfristig in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne befristet in Frankfurt.") == "Frankfurt"
    assert extract_residence_city("Ich arbeite befristet in Frankfurt.") == ""
    assert extract_residence_city("Ich wohne zur Miete in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne zur Zwischenmiete in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne zur Untermiete in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne bis auf Weiteres in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne bis zum Ende des Monats in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe bis Ende des Jahres bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne bis Jahresende in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin bis zum Ende des Monats.") == "Berlin"
    assert extract_residence_city("Ich wohne bis zum Jahresende in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin bis zum Jahresende.") == "Berlin"
    assert extract_residence_city("Ich wohne bis morgen in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin bis morgen.") == "Berlin"
    assert extract_residence_city("Ich wohne bis Ende der Woche in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin bis Ende der Woche.") == "Berlin"
    assert extract_residence_city("Ich wohne während dieser Woche in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne während des Monats in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Leipzig bis auf Weiteres.") == "Leipzig"
    assert extract_residence_city("Ich arbeite während der Ausbildung in Berlin.") == ""
    assert extract_residence_city("Ich wohne bei meiner Arbeit in Berlin.") == ""


def test_extract_residence_city_from_time_and_activity_markers() -> None:
    assert extract_residence_city("Ich wohne mit meiner Arbeit in Berlin.") == ""
    assert extract_residence_city("Ich wohne zusammen mit meinem Studium in Berlin.") == ""
    assert extract_residence_city("Ich wohne neben Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne von Montag bis Freitag in Berlin.") == ""
    assert extract_residence_city("Ich wohne täglich in Hamburg.") == ""
    assert extract_residence_city("Ich wohne nachts in Potsdam.") == ""
    assert extract_residence_city("Ich wohne jeden Tag in Dresden.") == ""
    assert extract_residence_city("Ich wohne nur am Wochenende in Berlin.") == ""
    assert extract_residence_city("Früher wohnte ich in Hamburg, jetzt in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne nunmehr in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit gestern in Berlin.") == "Berlin"
    assert extract_residence_city("In Zukunft wohne ich in Berlin.") == ""
    assert extract_residence_city("Ich wohne bereits in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne schon in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne noch in Berlin.") == "Berlin"


def test_extract_residence_city_from_clarification_forms() -> None:
    assert extract_residence_city("Ich wohne in Brandenburg bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber genauer gesagt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort ist Berlin, genauer gesagt Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort wird Berlin genannt.") == "Berlin"
    assert extract_residence_city("Ich wohne bei meinen Eltern, in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Zuhause heißt Berlin.") == "Berlin"


def test_extract_residence_city_from_address_conflict_forms() -> None:
    assert extract_residence_city("Meine Wohnadresse liegt nicht in Berlin, sondern in Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine alte Wohnadresse war Berlin, aktuell ist sie Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Adresse lautet 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meine Privatadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine private Adresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine Hauptadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Wohnadresse ist Potsdam.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber mein Lebensmittelpunkt ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin, mein Zuhause Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, zu Hause bin ich in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber mein Zuhause ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber mein Wohnort ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg ist meine Wohnung.") == ""
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist meine aktuelle Wohnung.") == ""
    assert extract_residence_city("Ich bin in Berlin wohnhaft bis morgen.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin ansässig bis morgen.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin wohnhaft ab morgen.") == ""
    assert extract_residence_city("Berlin bin ich wohnhaft bis morgen.") == "Berlin"
    assert extract_residence_city("Berlin bin ich wohnhaft ab morgen.") == ""
    assert extract_residence_city("Berlin ist meine vorübergehende Wohnadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist meine dauerhafte Wohnadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist meine vorläufige Wohnadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist meine zukünftige Wohnadresse.") == ""
    assert extract_residence_city("Berlin ist ab sofort meine Hauptadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist vorübergehend meine Wohnadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist bis zum Jahresende meine Wohnadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Wohnadresse seit gestern.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Wohnadresse ab morgen.") == ""
    assert extract_residence_city("Berlin ist meine Wohnadresse gewesen.") == ""
    assert extract_residence_city("Berlin ist meine Meldeadresse ab morgen.") == ""
    assert extract_residence_city("Berlin ist seit gestern mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist ab sofort mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist bis zum Jahresende mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort seit gestern.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort ab morgen.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort gewesen.") == ""
    assert extract_residence_city("Berlin ist meistens mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist normalerweise mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist überwiegend mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist regelmäßig mein Wohnort.") == ""


def test_extract_residence_city_from_final_move_forms() -> None:
    assert extract_residence_city("Nicht mehr in Berlin, sondern in Hamburg wohne ich.") == "Hamburg"
    assert extract_residence_city("Früher war mein Wohnort Hamburg. Jetzt ist er Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort wird ab morgen Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort soll Hamburg werden.") == ""
    assert extract_residence_city("Ich bin gerade nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin vor kurzem nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin vor zwei Wochen nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit meinem Umzug in Berlin.") == "Berlin"


def test_extract_residence_city_from_global_city_forms() -> None:
    assert extract_residence_city("Ich wohne in der Nähe Paris.") == "Paris"
    assert extract_residence_city("Ich wohne in Großbritannien.") == ""
    assert extract_residence_city("Ich wohne in Kanada.") == ""
    assert extract_residence_city("Ich wohne in Japan.") == ""
    assert extract_residence_city("Ich wohne in Amerika.") == ""
    assert extract_residence_city("Ich wohne in Kanada, genauer gesagt in Toronto.") == "Toronto"


def test_extract_residence_city_from_s_ending_relation_forms() -> None:
    assert extract_residence_city("Ich wohne außerhalb Paris.") == "Paris"
    assert extract_residence_city("Ich wohne südlich Paris.") == "Paris"
    assert extract_residence_city("Ich wohne am Rand Paris.") == "Paris"
    assert extract_residence_city("Ich wohne im Umland Paris.") == "Paris"
    assert extract_residence_city("Ich wohne im Norden Paris.") == "Paris"
    assert extract_residence_city("Ich wohne in der Nähe des Zentrums von Berlin.") == "Berlin"


def test_extract_residence_city_from_inverted_location_forms() -> None:
    assert extract_residence_city("In Berlin wohne ich.") == "Berlin"
    assert extract_residence_city("Dort, in Berlin, wohne ich.") == "Berlin"
    assert extract_residence_city("Hier, in Berlin, wohne ich.") == "Berlin"
    assert extract_residence_city("Da, in Berlin, lebe ich.") == "Berlin"
    assert extract_residence_city("Berlin, dort wohne ich.") == "Berlin"
    assert extract_residence_city("In Hamburg lebe ich.") == "Hamburg"
    assert extract_residence_city("Bei meinen Eltern in Berlin wohne ich.") == "Berlin"
    assert extract_residence_city("In der Nähe von Potsdam lebe ich.") == "Potsdam"
    assert extract_residence_city("Im Raum Leipzig wohne ich.") == "Leipzig"
    assert extract_residence_city("In Berlin habe ich meinen Wohnsitz.") == "Berlin"
    assert extract_residence_city("In Berlin bin ich zu Hause.") == "Berlin"
    assert extract_residence_city("In Berlin befindet sich mein Wohnort.") == "Berlin"
    assert extract_residence_city("In Berlin liegt mein Wohnsitz.") == "Berlin"
    assert extract_residence_city("In Berlin arbeite ich.") == ""
    assert extract_residence_city("In Berlin wohne ich nicht.") == ""
    assert extract_residence_city("In Berlin ist mein Arbeitsort.") == ""


def test_extract_residence_city_from_nearby_location_phrase() -> None:
    assert extract_residence_city("Ich wohne in der Nähe von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht weit von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Umgebung von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe im Raum Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich bin in der Nähe von Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich bin in der Umgebung von Potsdam ansässig.") == "Potsdam"
    assert extract_residence_city("Ich bin nahe Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Ich bin bei Hamburg beruflich ansässig.") == ""
    assert extract_residence_city("Ich wohne unweit von Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne in der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Einzugsgebiet von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in der Peripherie von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Metropolregion von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Gebiet um Bonn.") == "Bonn"
    assert extract_residence_city("Ich arbeite in der Peripherie von Hamburg.") == ""
    assert extract_residence_city("Ich lebe auf dem Dorf bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Landkreis München.") == "München"
    assert extract_residence_city("Ich wohne im Kreis Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich arbeite im Landkreis München.") == ""


def test_extract_residence_city_from_time_qualified_residence_phrase() -> None:
    assert extract_residence_city("Seit 2024 lebe ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe seit 2024 in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit kurzem in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit einiger Zeit in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne seit ein paar Jahren in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne seit zwei Jahren in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit mehr als zwei Jahren in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit über einem Jahr in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit knapp drei Monaten in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe seit etwa sechs Wochen in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne seit ungefähr einem Jahr in Dresden.") == "Dresden"
    assert extract_residence_city("Ich lebe seit gut zwei Jahren in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne seit fast zwei Jahren in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit circa einem Jahr in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit ca. drei Monaten in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne seit rund vier Jahren in Dresden.") == "Dresden"
    assert extract_residence_city("Ich lebe seit mindestens einem Jahr in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne schon seit 2020 in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe schon lange in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit Jahren in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne seit Monaten in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne momentan in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne nun in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nun Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause bleibt nun Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne heute in Dresden.") == ""
    assert extract_residence_city("Ich wohne vorübergehend in Bonn.") == "Bonn"
    assert extract_residence_city("Seitdem wohne ich in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne hier in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe direkt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne weiterhin in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe nach wie vor in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne noch immer in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich lebe immer noch in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohn seit zwei Jahren in Köln.") == "Köln"
    assert extract_residence_city("Ich wohn weiterhin in Berlin.") == "Berlin"
    assert extract_residence_city("Wohn seit 2020 in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nur in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne allein in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne momentan nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit dem letzten Jahr in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe seit dem vergangenen Jahr in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit meiner Kindheit in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe seit meiner Geburt in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne seit jeher in Bonn.") == "Bonn"
    assert extract_residence_city("Ich lebe seit dem Studium in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne seit letztem Sommer in Frankfurt.") == "Frankfurt"


def test_extract_residence_city_from_home_phrase() -> None:
    assert extract_residence_city("Ich bin in Berlin zuhause.") == "Berlin"
    assert extract_residence_city("Ich bin in Hamburg zu Hause.") == "Hamburg"
    assert extract_residence_city("Ich bin in Hamburg dahoam.") == "Hamburg"
    assert extract_residence_city("Ich bin aktuell in Potsdam zuhause.") == "Potsdam"
    assert extract_residence_city("Ich bin seit kurzem in Leipzig zu Hause.") == "Leipzig"
    assert extract_residence_city("Ich wohne zu Hause in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne zuhause in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich arbeite zu Hause in Berlin.") == ""
    assert extract_residence_city("Seit 2024 bin ich in Köln zu Hause.") == "Köln"
    assert extract_residence_city("Ich bin hier in Potsdam zuhause.") == "Potsdam"
    assert extract_residence_city("Das ist mein Zuhause in Berlin.") == "Berlin"
    assert extract_residence_city("Das ist unser Zuhause bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Potsdam bleibt unser Zuhause.") == "Potsdam"
    assert extract_residence_city("Berlin ist meine Bleibe.") == "Berlin"
    assert extract_residence_city("Hamburg ist unsere feste Bleibe.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Dresden.") == "Dresden"
    assert extract_residence_city("Mein Zuhause lautet Hamburg.") == "Hamburg"
    assert extract_residence_city("Zu Hause bin ich in Köln.") == "Köln"
    assert extract_residence_city("Ich bin bei meiner Freundin zuhause.") == ""


def test_extract_residence_city_after_person_or_household_phrase() -> None:
    assert extract_residence_city("Ich wohne bei meiner Freundin in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne gemeinsam mit meiner Freundin in Dresden.") == "Dresden"
    assert extract_residence_city("Ich arbeite gemeinsam mit meiner Freundin in Dresden.") == ""
    assert extract_residence_city("Ich wohne neben meiner Familie in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne neben meiner Arbeit in Berlin.") == ""
    assert extract_residence_city("Ich wohne im Herzen von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe im Herzen Berlins.") == "Berlin"
    assert extract_residence_city("Ich arbeite im Herzen von Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlins Gegend.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin an der Spree.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg am Rhein.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin an der Spree.") == ""
    assert extract_residence_city("Ich wohne am See bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe am See nahe Berlin.") == "Berlin"
    assert extract_residence_city("Ich arbeite am See bei Potsdam.") == ""
    assert extract_residence_city("Wir wohnen zusammen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Wir arbeiten zusammen in Berlin.") == ""
    assert extract_residence_city("Ich wohne aktuell: Dresden.") == "Dresden"
    assert extract_residence_city("Ich lebe derzeit: Bonn.") == "Bonn"
    assert extract_residence_city("Aktuell wohne ich: Hamburg.") == "Hamburg"
    assert extract_residence_city("Derzeit leben wir: Potsdam.") == "Potsdam"
    assert extract_residence_city("Wo ich wohne? In Berlin.") == "Berlin"
    assert extract_residence_city("Wo lebe ich: in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich arbeite aktuell: Hamburg.") == ""
    assert extract_residence_city("Ich wohne aktuell bei meiner Freundin in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe seit einiger Zeit bei meiner Freundin in Dresden.") == "Dresden"
    assert extract_residence_city("Seit 2024 wohne ich bei meinen Eltern in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne direkt bei meiner Freundin in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne mit meiner Familie bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe mit meinem Partner bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne bei meinen Eltern bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Wir leben zusammen mit unseren Kindern bei Leipzig.") == "Leipzig"


def test_extract_residence_city_from_plain_negated_change() -> None:
    assert extract_residence_city("Ich lebe nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht in Berlin, sondern in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht in Berlin sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne zwar in Berlin, aber in Hamburg lebe ich.") == "Hamburg"
    assert extract_residence_city("Ich lebe zwar in Berlin, aber in Hamburg wohne ich.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht in Berlin.") == ""


def test_extract_residence_city_from_move_phrases() -> None:
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin umgezogen von Berlin nach Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich bin nach Leipzig gezogen.") == "Leipzig"
    assert extract_residence_city("Ich bin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin aus Berlin nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin in Berlin nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin in Berlin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin aus Berlin nach Hamburg umgezogen.") == "Hamburg"


def test_extract_residence_city_handles_subjectless_move_fragment() -> None:
    assert extract_residence_city("Von Hamburg nach Berlin gezogen.") == "Berlin"
    assert extract_residence_city("Aus Hamburg nach Berlin umgezogen.") == "Berlin"
    assert extract_residence_city("Sie ist von Hamburg nach Berlin gezogen.") == ""
    assert extract_residence_city("Ich zog von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gewechselt.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg weggezogen.") == "Hamburg"
    assert extract_residence_city("Ich wechselte von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wechselten aus Berlin zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wechsle von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin nach dem Umzug nach Bonn gezogen.") == "Bonn"
    assert extract_residence_city("Ich bin nach meinem Umzug in Bonn umgezogen.") == "Bonn"
    assert extract_residence_city("Ich habe meinen Wohnort von Berlin nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort wurde nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort änderte sich zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort änderte sich von Berlin zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort wechselte von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz wechselte zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort verlegte sich nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort hat sich von Berlin nach Hamburg geändert.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort hat sich von Berlin zu Hamburg verändert.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort hat sich nach Hamburg geändert.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Wohnort nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Hamburg ist jetzt mein neuer Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist nun unser neuer Wohnsitz.") == "Berlin"
    assert extract_residence_city("Ich werde nach Hamburg ziehen.") == ""
    assert extract_residence_city("Ich werde in Hamburg wohnen.") == ""
    assert extract_residence_city("Ich soll in Hamburg wohnen.") == ""
    assert extract_residence_city("Ich könnte in Hamburg wohnen.") == ""
    assert extract_residence_city("Ich möchte in Hamburg wohnen.") == ""
    assert extract_residence_city("Ich moechte in Hamburg wohnen.") == ""
    assert extract_residence_city("Ich plane, in Hamburg zu wohnen.") == ""
    assert extract_residence_city("Ich beabsichtige, in Hamburg zu wohnen.") == ""
    assert extract_residence_city("Ich habe vor, in Hamburg zu wohnen.") == ""


def test_extract_residence_city_from_wonen_leben_change() -> None:
    assert extract_residence_city("Ich wohne in Berlin, lebe aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite jetzt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohnte in Berlin, lebe aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebte in Berlin, wohne aber nun in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich war in Berlin wohnhaft, bin jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohnte in Berlin, arbeite aber jetzt in Hamburg.") == ""
    assert extract_residence_city("Ich habe mich in Berlin niedergelassen.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin sesshaft.") == "Berlin"
    assert extract_residence_city("Ich habe mich bei Hamburg angesiedelt.") == "Hamburg"
    assert extract_residence_city("Ich bin in Potsdam eingezogen.") == "Potsdam"
    assert extract_residence_city("Ich bin nach Leipzig eingezogen.") == "Leipzig"
    assert extract_residence_city("Ich bin in Dresden sesshaft geworden.") == "Dresden"
    assert extract_residence_city("Ich ließ mich in Berlin nieder.") == "Berlin"
    assert extract_residence_city("Ich werde mich in Hamburg niederlassen.") == ""
    assert extract_residence_city("Ich will in Potsdam einziehen.") == ""
    assert extract_residence_city("Ich wohne in meiner Wohnung in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in meinem Haus bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in einer WG in Potsdam.") == "Potsdam"
    assert extract_residence_city("Wir wohnen in unserem Haus in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne im Haus in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne im Wohnheim in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in einem Studentenwohnheim bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in einem Mehrfamilienhaus in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne im Internat in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in einer Übergangswohnung in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe in einer Zwischenwohnung bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe eine feste Unterkunft in Berlin.") == "Berlin"
    assert extract_residence_city("Meine feste Unterkunft befindet sich in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich miete eine Wohnung in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe eine Mietwohnung in Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe in Köln eine Bleibe.") == "Köln"
    assert extract_residence_city("Ich habe eine Wohnung in Berlin.") == ""
    assert extract_residence_city("Ich besitze ein Haus in Hamburg.") == ""


def test_extract_residence_city_from_current_location_label() -> None:
    assert extract_residence_city("Mein aktueller Wohnort ist Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort lautet Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort befindet sich Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine aktuelle Stadt ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein jetziger Ort ist Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein aktueller Wohnort: Leipzig.") == "Leipzig"
    assert extract_residence_city("Wohnort: Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe meinen Wohnsitz in München.") == "München"
    assert extract_residence_city("Ich bin in Köln wohnhaft.") == "Köln"
    assert extract_residence_city("Berlin ist mein Wohnort.") == "Berlin"
    assert extract_residence_city("Wohnhaft in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin ansässig in Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Zuhause liegt in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort befindet sich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz ist in Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine aktuelle Wohnstadt ist Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnort ist in der Nähe von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt in der Umgebung von Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Wohnstadt befindet sich im Raum Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Zuhause ist nahe Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein Wohnort liegt unweit von Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnort ist in der Stadt Köln.") == "Köln"
    assert extract_residence_city("Mein Zuhause ist die Stadt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist der Ort Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Arbeitsort ist die Stadt Hamburg.") == ""
    assert extract_residence_city("Ich wohne an dem Ort Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe an dem Ort Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in dem Ort Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne am Ort Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe am Ort Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich arbeite an dem Ort Berlin.") == ""
    assert extract_residence_city("Mein derzeitiger Wohnort: Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein gegenwärtiger Ort ist Köln.") == "Köln"
    assert extract_residence_city("Heute ist mein Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Seit heute ist mein Wohnsitz Hamburg.") == "Hamburg"
    assert extract_residence_city("Nun ist mein Zuhause in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit 2020 ist mein Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Seit Jahren ist Berlin mein Wohnort.") == "Berlin"
    assert extract_residence_city("Seit Jahren ist Berlin mein Arbeitsort.") == ""
    assert extract_residence_city("Seit kurzem liegt mein Wohnsitz in Hamburg.") == "Hamburg"
    assert extract_residence_city("Seit einiger Zeit befindet sich mein Zuhause in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit zwei Jahren ist mein Hauptwohnsitz Dresden.") == "Dresden"
    assert extract_residence_city("Seit meiner Kindheit ist mein Wohnort Leipzig.") == "Leipzig"
    assert extract_residence_city("Seit 2020 ist mein Wohnort nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Seit 2020 ist mein Wohnort in Deutschland, genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Heute ist mein Wohnsitz in der Schweiz, nämlich bei Zürich.") == "Zürich"
    assert extract_residence_city("Seit kurzem liegt mein Zuhause in Deutschland, konkret in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz liegt im Bundesland Sachsen, in Leipzig.") == "Leipzig"
    assert extract_residence_city("Meine Wohnstadt bleibt weiterhin im Bundesland Sachsen, in Leipzig.") == "Leipzig"
    assert extract_residence_city("Heute bin ich in Deutschland, genauer gesagt in Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Heute bin ich in der Schweiz, konkret bei Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Seit 2020 bin ich in Deutschland, und zwar in Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist weiterhin Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort bleibt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist nach wie vor Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnort ist noch immer Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein Wohnort bleibt weiterhin in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist noch immer in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist nicht Berlin sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist nun nicht mehr Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz ist jetzt nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin, aber jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin und ist jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin, ist aber jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war früher Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin, nun in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin, inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin, jetzt arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohnte früher in Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohnte in Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin, aber ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin; jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist in Berlin – inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist in Berlin und jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Wohnstadt ist in Berlin, mittlerweile in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz liegt in Berlin, inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist in Berlin, aktuell arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich bin weiterhin in Potsdam wohnhaft.") == "Potsdam"
    assert extract_residence_city("Seit zwei Jahren bin ich in Leipzig wohnhaft.") == "Leipzig"
    assert extract_residence_city("Derzeit bin ich in Dresden ansässig.") == "Dresden"
    assert extract_residence_city("In Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich bin seit 2020 in Bonn ansässig.") == "Bonn"
    assert extract_residence_city("Mein Zuhause bleibt in Köln.") == "Köln"
    assert extract_residence_city("Mein Zuhause ist weiterhin in Frankfurt.") == "Frankfurt"
    assert extract_residence_city("Mein Zuhause liegt nach wie vor in München.") == "München"
    assert extract_residence_city("Mein Zuhause ist nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause befindet sich nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin, aber jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause war Berlin, aber jetzt ist es Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause war Berlin, heute liegt es in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin, jetzt aber Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin, jetzt aber Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause war Berlin, heute arbeite ich in Hamburg.") == ""
    assert extract_residence_city("Mein Zuhause liegt in Berlin, aber inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause war Berlin und ist jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin, aber ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und nicht in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und lebe nicht in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und lebe in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und bin heute müde.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und besuche Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und verbringe die Wochenenden in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und treffe Freunde in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und reise oft nach Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und pendle nach Hamburg.") == "Berlin"


def test_extract_residence_city_from_full_address_phrases() -> None:
    assert extract_residence_city("Ich wohne in der Hauptstraße 12 in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe bei 20095 Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist 14467 Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnort: 04109 Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich lebe in der Musterstraße 4a bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Bahnhofstraße 8, Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine Adresse ist Hauptstraße 12, Berlin.") == "Berlin"
    assert extract_residence_city("Meine Adresse ist Hauptstraße 12, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse lautet Musterweg 3 in Dresden.") == "Dresden"
    assert extract_residence_city("Meine Wohnadresse lautet Musterweg 3, 01067 Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnsitz ist Lindenallee 7, Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich habe meine Anschrift in der Bahnhofstraße 2 in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne in Berlin ohne Hausnummer.") == "Berlin"
    assert extract_residence_city("Ich arbeite in der Hauptstraße 12 in Berlin.") == ""
    assert extract_residence_city("Ich arbeite in 10115 Berlin.") == ""
    assert extract_residence_city("Meine Geschäftsadresse ist Hauptstraße 12 in Hamburg.") == ""
    assert extract_residence_city("Ich war in der Hauptstraße 12 in Berlin zu Besuch.") == ""


def test_extract_residence_city_rejects_conflicting_private_addresses() -> None:
    assert extract_residence_city("Ich wohne in Berlin; meine Adresse ist Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin, meine Adresse ist Hamburg.") == ""
    assert extract_residence_city("Ich lebe in Berlin, mein Wohnsitz ist Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, meine Wohnadresse ist Hamburg.") == ""
    assert extract_residence_city("Meine Adresse ist Hamburg, ich wohne in Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin, meine Arbeitsadresse ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Geschäftsadresse ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Postadresse ist Hamburg.") == "Berlin"


def test_extract_residence_city_rejects_negated_or_non_city_phrases() -> None:
    for text in (
        "Ich wohne in keiner Stadt, sondern auf dem Land.",
        "Ich wohne bei meiner Mutter.",
        "Mein Wohnort ist nicht Berlin.",
        "Meine Heimatstadt ist Hamburg.",
        "Mein Zuhause ist nicht Berlin.",
        "Berlin ist mein Arbeitsort.",
        "Hamburg ist mein Herkunftsort.",
        "Ich wohne in Berlin nicht mehr.",
    ):
        assert extract_residence_city(text) == ""


def test_extract_residence_city_prefers_explicit_current_residence_after_origin() -> None:
    assert extract_residence_city("Ich komme aus Deutschland und lebe jetzt in Berlin.") == "Berlin"


def test_extract_residence_city_handles_current_city_after_residence_change() -> None:
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern nahe Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern in der Nähe von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern nahe Potsdam arbeite ich.") == ""
    assert extract_residence_city("Ich wohne in Berlin nicht mehr, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr bei meiner Mutter, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, doch jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, jedoch jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin; doch inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin – jedoch nun in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe nicht in Berlin, aber jetzt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, aber jetzt in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Berlin, aber inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, lebe aber inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, inzwischen in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Berlin, seitdem in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne in Berlin; jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin – inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht in Berlin; sondern in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin – jetzt in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Berlin und lebe jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin und lebe inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, aber lebe seit 2020 in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne in Berlin, lebe aber seit kurzem in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Berlin, seit 2020 lebe ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, inzwischen lebe ich in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite jetzt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite inzwischen in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin; aber arbeite jetzt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne mit meiner Ausbildung in Köln.") == ""
    assert extract_residence_city("Ich wohne bei meiner Firma in Berlin.") == ""
    assert extract_residence_city("Ich wohne bei meinem Chef in Hamburg.") == ""
    assert extract_residence_city("Ich wohne nicht in Berlin; aber arbeite jetzt in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite seit 2020 in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne zwar in Berlin, aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne zwar in Berlin, aber arbeite aktuell in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne zuhause in Berlin, aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nur noch zuhause in Berlin, aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nur noch in Berlin, aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne zuhause in Berlin – aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nur noch zuhause in Berlin.") == "Berlin"


def test_extract_residence_city_removes_daypart_context() -> None:
    assert extract_residence_city("Ich wohne in Hamburg nachts.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin schon seit Jahren.") == "Berlin"
    assert extract_residence_city("Ich wohne in Potsdam für zwei Jahre.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin während meines Studiums.") == "Berlin"
    assert extract_residence_city("Ich wohne in München zusammen mit meinen Eltern.") == "München"
    assert extract_residence_city("Ich wohne in Berlin in einer WG.") == "Berlin"
    assert extract_residence_city("Ich wohne im Stadtteil Kreuzberg in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe im Bezirk Neukölln bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Viertel Altona in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe im Kiez von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Stadtteil von Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein Wohnort liegt im Bezirk Neustadt in Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnsitz befindet sich im Viertel Mitte bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Altstadt von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe im Stadtzentrum von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Zentrum von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe in der Innenstadt von Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne im Ortsteil Prenzlauer Berg in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Quartier Altstadt bei Zürich.") == "Zürich"
    assert extract_residence_city("Mein Wohnort liegt im Ortsteil Plagwitz in Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein Zuhause befindet sich in der Altstadt von Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne im Ortsteil Prenzlauer Berg.") == ""
    assert extract_residence_city("Ich wohne im Stadtteil Kreuzberg und arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Stadtteil Kreuzberg in Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich arbeite im Bezirk Mitte in Berlin.") == ""
    assert extract_residence_city("Ich lebe in Hamburg auf dem Land.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Potsdam neben meinen Eltern.") == "Potsdam"
    assert extract_residence_city("Ich lebe in Dresden nahe der Innenstadt.") == "Dresden"
    assert extract_residence_city("Ich wohne in Köln innerhalb der Stadt.") == "Köln"
    assert extract_residence_city("Ich wohne in Berlin aus beruflichen Gründen.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg wegen der Arbeit.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin als Student.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin obwohl ich in Hamburg arbeite.") == "Berlin"
    assert extract_residence_city("Ich wohne in Potsdam wobei ich in Berlin studiere.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Köln denn dort ist meine Familie.") == "Köln"
    assert extract_residence_city("Ich wohne in München da meine Familie dort ist.") == "München"
    assert extract_residence_city("Ich wohne in Berlin im Norden.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg am Stadtrand.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Potsdam am See.") == "Potsdam"
    assert extract_residence_city("Ich lebe in Leipzig im Zentrum.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Frankfurt am Main.") == "Frankfurt am Main"
    assert extract_residence_city("Ich wohne in Berlin oder Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin sowie in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin - meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Bad Homburg-Süd.") == "Bad Homburg-Süd"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt lebe ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin! Inzwischen wohne ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin. Jetzt wohne ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin. Nun lebe ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt arbeite ich in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin. Jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin. Inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin zurzeit.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin zur Zeit.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg momentan.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Potsdam derzeit.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Bonn vorübergehend.") == "Bonn"
    assert extract_residence_city("Ich wohne in Köln derzeit bei meinen Eltern.") == "Köln"
    assert extract_residence_city("Ich wohne in Berlin/Brandenburg.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin/Brandenburg.") == ""
    assert extract_residence_city("Ich wohne in Hamburg & Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin-Brandenburg.") == "Berlin-Brandenburg"
    assert extract_residence_city("Ich wohne in Berlin / arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin & meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin. Jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht in Berlin. Sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in St. Gallen.") == "St. Gallen"
    assert extract_residence_city("Mein Wohnort ist in der Stadt.") == ""
    assert extract_residence_city("Mein Wohnort ist in der Nähe.") == ""
    assert extract_residence_city("Mein Wohnort ist bei der Arbeit.") == ""
    assert extract_residence_city("Mein Zuhause ist nahe.") == ""
    assert extract_residence_city("Mein Wohnort ist außerhalb von Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist unter Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist aus Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist für Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist wegen Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist neben Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist während Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist in Amberg.") == "Amberg"
    assert extract_residence_city("Mein Wohnort ist in Aufhausen.") == "Aufhausen"
    assert extract_residence_city("Mein Wohnort ist Mühlhausen/Thüringen.") == "Mühlhausen/Thüringen"
    assert extract_residence_city("Mein Wohnort ist Muehlhausen/Thueringen.") == "Mühlhausen/Thüringen"
    assert extract_residence_city("Ich arbeite in Hamburg, aber wohne in Frankfurt (Oder).") == "Frankfurt (Oder)"
    assert extract_residence_city("Ich arbeite in Hamburg, wohne aber in Frankfurt (Oder).") == "Frankfurt (Oder)"
    assert extract_residence_city("Mein Wohnort ist der Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist dieser Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist dort Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist den Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist welcher Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist mehrere Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist in Dortmund.") == "Dortmund"
    assert extract_residence_city("Mein Lebensmittelpunkt ist Berlin.") == "Berlin"
    assert extract_residence_city("Mein Lebensmittelpunkt liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Lebensmittelpunkt in Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein Hauptwohnsitz ist in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe meinen Hauptwohnsitz in Dresden.") == "Dresden"
    assert extract_residence_city("Ich lebe überwiegend in Bonn.") == "Bonn"
    assert extract_residence_city("Ich lebe hauptsächlich in Köln.") == "Köln"
    assert extract_residence_city("Meine Heimat ist München.") == ""
    assert extract_residence_city("Mein Lebensmittelpunkt ist Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Hauptwohnsitz ist nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Lebensmittelpunkt war Berlin, inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Lebensmittelpunkt war Hamburg, jetzt Berlin.") == "Berlin"
    assert extract_residence_city("Mein Lebensmittelpunkt war Hamburg, jetzt arbeite in Berlin.") == ""
    assert extract_residence_city("Mein Hauptwohnsitz wurde nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort wurde von Berlin nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz wurde aus Berlin nach Potsdam verlegt.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort ist von Berlin nach Hamburg gewechselt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist von Berlin nach Hamburg geblieben.") == ""
    assert extract_residence_city("Berlin war mein Wohnort, jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher war Berlin mein Wohnort, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ehemals war Berlin mein Wohnsitz, jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin war mein Wohnort, jetzt arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohnte in Berlin. Jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebte in Berlin. Heute Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mehr mein Wohnort. Jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohnte in Berlin. Jetzt arbeite in Hamburg.") == ""
    assert extract_residence_city("Früher ansässig in Berlin, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Damals gemeldet in Berlin, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ehemals registriert bei Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher ansässig in Berlin, heute arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich habe meinen Hauptwohnsitz nach Potsdam verlegt.") == "Potsdam"
    assert extract_residence_city("Mein Lebensmittelpunkt: Berlin.") == "Berlin"
    assert extract_residence_city("Hauptwohnsitz: Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Hauptwohnsitz: Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Hauptwohnsitz ist dauerhaft in Bonn.") == "Bonn"
    assert extract_residence_city("Mein Wohnort ist dauerhaft Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne dauerhaft in Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe meinen festen Wohnsitz in Köln.") == "Köln"
    assert extract_residence_city("Ich habe einen festen Wohnsitz in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe einen dauerhaften Wohnsitz in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe einen Hauptwohnsitz in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe einen festen Lebensmittelpunkt in Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe meinen privaten Wohnsitz in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich habe meinen offiziellen Wohnsitz in Bonn.") == "Bonn"
    assert extract_residence_city("Meine offizielle Adresse ist Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine dauerhafte Adresse ist Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine feste Wohnanschrift liegt in Berlin.") == "Berlin"
    assert extract_residence_city("Meine stabile Adresse befindet sich in Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein dienstlicher Wohnsitz ist Hamburg.") == ""
    assert extract_residence_city("Ich habe einen ständigen Wohnort in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe einen permanenten Hauptwohnsitz bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe den Hauptwohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe den Lebensmittelpunkt bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen in Berlin.") == "Berlin"
    assert extract_residence_city("Wir leben seit zwei Jahren in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir haben Berlin als Wohnort.") == "Berlin"
    assert extract_residence_city("Wir wohnen derzeit in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit 2020 wohnen wir in Leipzig.") == "Leipzig"
    assert extract_residence_city("Seit 2020 sind wir in Leipzig wohnhaft.") == "Leipzig"
    assert extract_residence_city("Wir haben unseren Wohnsitz in Dresden.") == "Dresden"
    assert extract_residence_city("Wir wohnen nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen nicht mehr in Berlin. Jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnten in Berlin, jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir sind in Berlin ansässig.") == "Berlin"
    assert extract_residence_city("Wir sind seit 2020 in Leipzig ansässig.") == "Leipzig"
    assert extract_residence_city("Wir wohnen in Berlin und leben in Hamburg.") == ""
    assert extract_residence_city("Wir wohnen in Berlin und arbeiten in Hamburg.") == "Berlin"
    assert extract_residence_city("Wir wohnen in Berlin und studieren in Hamburg.") == "Berlin"
    assert extract_residence_city("Wir wohnen in Berlin und unser Wohnort ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen in Berlin und unser Arbeitsort ist Hamburg.") == "Berlin"
    assert extract_residence_city("Unser Wohnort ist Berlin und Hamburg.") == ""
    assert extract_residence_city("Wir wohnen in Berlin und pendeln nach Hamburg.") == "Berlin"
    assert extract_residence_city("Wir wohnen in Berlin und sind in Hamburg.") == ""
    assert extract_residence_city("Wir wohnen in Berlin und sind beruflich in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Schweiz, in Zürich.") == "Zürich"
    assert extract_residence_city("Ich lebe in Deutschland, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland.") == ""
    assert extract_residence_city("Ich wohne in Österreich.") == ""
    assert extract_residence_city("Ich wohne in der Schweiz.") == ""
    assert extract_residence_city("Ich wohne im Bundesland Bayern, in München.") == "München"
    assert extract_residence_city("Ich lebe im Raum Berlin, in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, in Deutschland.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland, genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland, nämlich in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland, und zwar in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Bayern, in München.") == "München"
    assert extract_residence_city("Ich lebe in Nordrhein-Westfalen, in Köln.") == "Köln"
    assert extract_residence_city("Ich lebe in NRW, in Köln.") == "Köln"
    assert extract_residence_city("Ich lebe in NRW.") == ""
    assert extract_residence_city("Ich wohne in Berlin, genauer gesagt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nahe Berlin, genauer gesagt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne unweit von Berlin, genauer gesagt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Umland Berlins, genauer in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Umland von Berlin, genauer gesagt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne im Berliner Raum, genauer gesagt in Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnort: Berliner Nähe, genauer: Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort ist Berlin, konkret in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne auf dem Land bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe auf dem Land nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne auf dem Land in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne außerhalb von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe am Stadtrand von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Umland von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe südlich von Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort liegt westlich von Leipzig.") == "Leipzig"
    assert extract_residence_city("Jetzt wohne ich auf dem Land bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne jetzt auf dem Land, in Bremen.") == "Bremen"
    assert extract_residence_city("Jetzt lebe ich in einer kleinen Stadt bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer großen Stadt nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Dorf bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einem kleinen Dorf bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einem Vorort von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in der Vorstadt von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne auf dem Land in der Nähe von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist ein Dorf bei Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist eine Kleinstadt nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in einem Ort namens Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer Stadt genannt Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort nennt sich Berlin.") == "Berlin"
    assert extract_residence_city("Meine Adresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe meine Anschrift in Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine aktuelle Adresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine Adresse ist in Deutschland, genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort: Deutschland, Köln.") == "Köln"
    assert extract_residence_city("Wohnort: Deutschland, in Köln.") == "Köln"
    assert extract_residence_city("Wohnort: Deutschland, genauer Köln.") == "Köln"
    assert extract_residence_city("Meine Wohnadresse ist jetzt Berlin.") == "Berlin"
    assert extract_residence_city("Seit 2020 bin ich in Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Berlin lautet mein Wohnort.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse liegt in Österreich, konkret in Wien.") == "Wien"
    assert extract_residence_city("Meine Geschäftsadresse ist in Deutschland, genauer gesagt in Berlin.") == ""
    assert extract_residence_city("Meine jetzige Wohnadresse liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine derzeitige Anschrift befindet sich in Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine jetzige Wohnung liegt in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne inzwischen dauerhaft in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne nur vorübergehend in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne seit 2020 dauerhaft in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne hier weiterhin in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in einer Kleinstadt bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einem Dorf nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Großstadt Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer Stadt, nämlich Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in einer Stadt ohne konkrete Angabe.") == ""
    assert extract_residence_city("Ich wohne in einer Stadt.") == ""
    assert extract_residence_city("Mein Wohnort ist ein Dorf.") == ""
    assert extract_residence_city("Mein Wohnort nennt sich nicht Berlin.") == ""
    assert extract_residence_city("Meine Adresse ist nicht Berlin.") == ""
    assert extract_residence_city("Meine Geschäftsadresse ist Hamburg.") == ""
    assert extract_residence_city("Meine alte Adresse ist Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin, Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, Potsdam.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin, Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin, Deutschland.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Brandenburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland, Berlin.") == ""
    assert extract_residence_city("Ich war wohnhaft in Berlin.") == ""
    assert extract_residence_city("Früher war ich wohnhaft in Hamburg.") == ""
    assert extract_residence_city("Ehemals wohnhaft in Potsdam.") == ""
    assert extract_residence_city("Ich war ansässig in Dresden.") == ""
    assert extract_residence_city("Seit 2020 wohnhaft in Berlin.") == "Berlin"
    assert extract_residence_city("Derzeit wohnhaft in Hamburg.") == "Hamburg"
    assert extract_residence_city("Aktuell ansässig in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit kurzem wohnhaft bei Leipzig.") == "Leipzig"
    assert extract_residence_city("Nach wie vor ansässig in Dresden.") == "Dresden"
    assert extract_residence_city("Seit 2020 in Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Aktuell in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Mein ehemaliger Wohnort ist Potsdam.") == ""
    assert extract_residence_city("Mein früherer Wohnsitz liegt in Dresden.") == ""
    assert extract_residence_city("Mein früheres Zuhause ist Hamburg.") == ""
    assert extract_residence_city("Mein alter Wohnort ist Leipzig.") == ""
    assert extract_residence_city("Seit 2020 war mein Wohnort Berlin.") == ""
    assert extract_residence_city("Mein vormaliger Wohnsitz liegt in Hamburg.") == ""
    assert extract_residence_city("Ich wohne außerhalb von Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne außerhalb von Berlin und lebe in Hamburg.") == ""
    assert extract_residence_city("Ich wohne außerhalb von Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne rund um Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne nahe Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne unweit von Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Raum Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Großraum Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Grossraum Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Gebiet von Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne in der Berliner Region und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Berliner Raum und Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort liegt im Großraum Berlin und Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort liegt im Berliner Großraum und Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Großraum Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne im Raum Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne im Raum Berlin und Umgebung von Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Großraum Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne im Berliner Umland und Hamburg.") == ""
    assert extract_residence_city("Ich wohne außerhalb der Stadt Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne außerhalb der Stadt Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne rund um Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein damaliger Wohnort ist Dresden.") == ""
    assert extract_residence_city("Ich residiere in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe derzeit meinen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe aktuell meinen Hauptwohnsitz in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Wohnsitz derzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnung liegt derzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Meine neue Wohnung liegt in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Unterkunft befindet sich aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen aktuellen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen gemeldeten Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen jetzigen Wohnort in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe derzeit eine Wohnung in Berlin.") == ""
    assert extract_residence_city("Wir residieren bei Dresden.") == "Dresden"
    assert extract_residence_city("Ich bin in Leipzig gemeldet.") == "Leipzig"
    assert extract_residence_city("Ich bin gemeldet in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin offiziell in Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin offiziell gemeldet.") == "Berlin"
    assert extract_residence_city("Ich bin polizeilich in Hamburg gemeldet.") == "Hamburg"
    assert extract_residence_city("Ich bin privat in Potsdam ansässig.") == "Potsdam"
    assert extract_residence_city("Ich bin dauerhaft in Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Ich bin nur vorübergehend in Hamburg gemeldet.") == "Hamburg"
    assert extract_residence_city("Ich bin aktuell registriert bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin gegenwärtig bei Potsdam gemeldet.") == "Potsdam"
    assert extract_residence_city("Ich bin beruflich in Berlin ansässig.") == ""
    assert extract_residence_city("Bei Leipzig bin ich gemeldet.") == "Leipzig"
    assert extract_residence_city("Bei Berlin und Hamburg bin ich gemeldet.") == ""
    assert extract_residence_city("Ich bin gemeldet in Berlin und Hamburg.") == ""
    assert extract_residence_city("Meine Wohnung ist in Berlin.") == "Berlin"
    assert extract_residence_city("Unsere WG liegt bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Unterkunft befindet sich in Potsdam.") == "Potsdam"
    assert extract_residence_city("Meine alte Wohnung ist in Berlin.") == ""
    assert extract_residence_city("Meine Meldadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Mein Meldesitz liegt bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Unsere Meldeanschrift befindet sich in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe meine Bleibe in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe eine feste Bleibe in Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe eine Arbeitsbleibe in Berlin.") == ""
    assert extract_residence_city("Meine Bleibe ist in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich habe mein Zuhause in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe unser Zuhause bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Wir haben unser zu Hause in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt lebe ich in Deutschland, in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt wohne ich im Raum Berlin, in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt bin ich in Deutschland, in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Inzwischen bei Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Wir leben in der Nähe von Berlin.") == "Berlin"
    assert extract_residence_city("Wir wohnen nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen im Raum München.") == "München"
    assert extract_residence_city("Wir wohnen rund um Köln.") == "Köln"
    assert extract_residence_city("Wir sind dort in Potsdam ansässig.") == "Potsdam"
    assert extract_residence_city("Wir wohnen bei unseren Eltern in Köln.") == "Köln"
    assert extract_residence_city("Wir leben bei den Eltern in Berlin.") == "Berlin"
    assert extract_residence_city("Wir wohnen aktuell bei meiner Familie in Bonn.") == "Bonn"
    assert extract_residence_city("Wir wohnen zusammen mit unseren Eltern in Leipzig.") == "Leipzig"
    assert extract_residence_city("Wir wohnen mit unseren Kindern in München.") == "München"
    assert extract_residence_city("Wir leben mit Freunden in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne zusammen mit meinen Eltern in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne mit meinen Kindern in München.") == "München"
    assert extract_residence_city("Ich lebe mit Freunden in Dresden.") == "Dresden"
    assert extract_residence_city(
        "Ich wohne in Berlin. Jetzt lebe ich in Hamburg. Inzwischen wohne ich in Potsdam."
    ) == "Potsdam"
    assert extract_residence_city("Wir wohnen in Berlin. Jetzt in Hamburg. Inzwischen in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt wohne ich wieder in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt mit meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt im Raum Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg bin ich im Urlaub.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, doch inzwischen mit meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin - jetzt im Raum Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt mit meiner Arbeit in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt mit meinem Studium in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne nicht in Berlin, sondern bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist nicht Berlin, sondern bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, nun Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, jetzt arbeite in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aktuell bei Potsdam gemeldet.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, aktuell bei Potsdam registriert.") == "Potsdam"
    assert extract_residence_city("Meine alte Wohnadresse ist Berlin, meine neue ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine alte Adresse ist Berlin, meine neue ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Freundin wohnt in Hamburg, meiner ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin wohnt in Hamburg, meiner ist in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen, wohne aber bei Köln.") == "Köln"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen, wohne aber jetzt in Köln.") == "Köln"
    assert extract_residence_city("Ich zog von Berlin nach Hamburg, lebe aber inzwischen in Köln.") == "Köln"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen, wohne aber jetzt arbeite in Köln.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist heute Hamburg, gestern war es Berlin.") == "Hamburg"
    assert extract_residence_city("Ich wohne heute in Hamburg, gestern noch in Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort: heute Hamburg, gestern Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort: gestern Hamburg, heute Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg auf Besuch.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg im Urlaub.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg zum Urlaub.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg als Tourist.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt bei Freunden in Hamburg zu Besuch.") == "Berlin"
    assert extract_residence_city("Ich komme aus Berlin, wohne aber inzwischen in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe zwischen Berlin und Potsdam.") == ""
    assert extract_residence_city("Ich wohne irgendwo bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin beheimatet.") == "Berlin"


def test_extract_residence_city_from_colloquial_forms() -> None:
    assert extract_residence_city("Ich wohn in Berlin.") == "Berlin"
    assert extract_residence_city("Ich leb in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne grad in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne zurzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne dahoam in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin dahoam in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin daheim in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin zuhause in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin zu Hause in Berlin.") == "Berlin"
    assert extract_residence_city("I leb in Berlin.") == "Berlin"
    assert extract_residence_city("Berlin - da lebe ich.") == "Berlin"
    assert extract_residence_city("In Berlin leb ich.") == "Berlin"
    assert extract_residence_city("In Berlin wohn ich.") == "Berlin"
    assert extract_residence_city("Ich ha e meinen Wohnsitz in Berlin.") == ""


def test_extract_residence_city_rejects_semicolon_conflicts() -> None:
    assert extract_residence_city("Ich wohne in Berlin; Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin; Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin; aber ich arbeite in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_punctuated_clarifications() -> None:
    assert extract_residence_city("Ich wohne in Berlin, genauer gesagt: Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Deutschland; genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin; konkret: Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg und Köln.") == ""
    assert extract_residence_city("Ich wohne in Berlin, Hamburg sowie Köln.") == ""
    assert extract_residence_city("Ich wohne in Berlin, Hamburg und arbeite in Köln.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, auch in Hamburg zur Arbeit.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber auch in Hamburg beruflich.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Nähe von Berlin und in Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Ich wohne nahe Berlin und in Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Ich wohne im Umland von Berlin und in Hamburg arbeite ich.") == "Berlin"


def test_extract_residence_city_rejects_bare_label_conflicts() -> None:
    assert extract_residence_city("Wohnort Berlin, Hamburg.") == ""
    assert extract_residence_city("Wohnort: Berlin; Hamburg.") == ""
    assert extract_residence_city("Wohnort Berlin, Deutschland.") == "Berlin"


def test_extract_residence_city_resolves_bare_label_changes() -> None:
    assert extract_residence_city("Wohnort Berlin, genauer gesagt Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnort: Deutschland; genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort Berlin, aber jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Daheim: Berlin, aber jetzt Hamburg.") == "Hamburg"


def test_extract_residence_city_resolves_today_state_changes() -> None:
    assert extract_residence_city("Mein Wohnort war Berlin, jetzt ist er Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war Berlin, heute ist er Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher wohnte ich in Berlin, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher lebte ich in Berlin, heute in Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_nimmer_changes() -> None:
    assert extract_residence_city("Ich wohne nimmer in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich leb nimmer in Berlin, aber jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nimmer in Berlin.") == ""


def test_extract_residence_city_rejects_absolute_negation_labels() -> None:
    assert extract_residence_city("Ich wohne keinesfalls in Hamburg.") == ""
    assert extract_residence_city("Ich wohne keineswegs in Potsdam.") == ""
    assert extract_residence_city("Ich lebe niemals in Berlin.") == ""
    assert extract_residence_city("Ich wohne keinesfalls in Berlin, sondern in Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_frequency_qualifiers() -> None:
    assert extract_residence_city("Ich wohne oft in Berlin.") == ""
    assert extract_residence_city("Ich wohne meist in Hamburg.") == ""
    assert extract_residence_city("Ich wohne gelegentlich in Bonn.") == ""
    assert extract_residence_city("Ich wohne regelmäßig in Berlin.") == ""
    assert extract_residence_city("Ich lebe selten in Hamburg.") == ""
    assert extract_residence_city("Ich wohne manchmal in Berlin.") == ""
    assert extract_residence_city("Ich wohne meistens in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne überwiegend in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne hauptsächlich in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne normalerweise in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne gewöhnlich in Köln.") == "Köln"
    assert extract_residence_city("Ich wohne in der Regel in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne regulär in Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne üblicherweise in Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne manchmal in Berlin, meistens in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne meistens in Berlin, manchmal in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meistens in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne normalerweise in Berlin, im Urlaub in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, normalerweise in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne gewöhnlich in Berlin, im Urlaub in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, gewöhnlich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne normalerweise in Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne meistens in Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, normalerweise in Hamburg und Köln.") == ""
    assert extract_residence_city("Ich wohne in Berlin, meistens in Hamburg und Köln.") == ""
    assert extract_residence_city("Ich wohne normalerweise in Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne meistens in Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne meistens in Berlin und lebe in Hamburg.") == ""


def test_extract_residence_city_prefers_home_outside_temporary_travel() -> None:
    assert extract_residence_city("Im Urlaub wohne ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("In den Ferien lebe ich in Berlin, ansonsten in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während der Ferien wohne ich in Köln, sonst lebe ich in Bonn.") == "Bonn"
    assert extract_residence_city("Im Urlaub wohne ich in Berlin.") == ""
    assert extract_residence_city("Auf Dienstreise wohne ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Auf Reisen lebe ich in Berlin, ansonsten in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während einer Dienstreise wohne ich in Köln, sonst in Bonn.") == "Bonn"
    assert extract_residence_city("Am Wochenende wohne ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Unter der Woche lebe ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Montags wohne ich in Köln, ansonsten in Bonn.") == "Bonn"
    assert extract_residence_city("Am Wochenende wohne ich in Berlin.") == ""
    assert extract_residence_city("Während meines Urlaubs wohne ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während des Urlaubs lebe ich in Berlin, ansonsten in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während der Reise wohne ich in Köln, sonst in Bonn.") == "Bonn"
    assert extract_residence_city("Während eines Aufenthalts in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während meines Urlaubs wohne ich in Berlin.") == ""
    assert extract_residence_city("Bei Besuch wohne ich in Berlin, sonst in Hamburg.") == "Hamburg"
    assert extract_residence_city("Zu Besuch lebe ich in Berlin, ansonsten in Hamburg.") == "Hamburg"
    assert extract_residence_city("Während meines Besuchs wohne ich in Köln, sonst in Bonn.") == "Bonn"
    assert extract_residence_city("Bei Besuch wohne ich in Berlin.") == ""


def test_extract_residence_city_rejects_person_targets_without_city() -> None:
    assert extract_residence_city("Ich wohne bei Freunden.") == ""
    assert extract_residence_city("Ich wohne bei Bekannten.") == ""
    assert extract_residence_city("Ich wohne bei Kollegen.") == ""
    assert extract_residence_city("Ich wohne bei Freunden in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne bei meinen Eltern in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne gemeinsam mit meiner Partnerin.") == ""
    assert extract_residence_city("Ich wohne gemeinsam mit meiner Partnerin in Dresden.") == "Dresden"


def test_extract_residence_city_preserves_compound_city_names() -> None:
    assert extract_residence_city("Ich wohne in Frankfurt an der Oder.") == "Frankfurt an der Oder"
    assert extract_residence_city("Ich wohne in Ludwigshafen am Rhein.") == "Ludwigshafen am Rhein"
    assert extract_residence_city("Ich wohne in Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Ich wohne in Frankfurt am Main.") == "Frankfurt am Main"
    assert extract_residence_city("Ich wohne in Frankfurt (Oder).") == "Frankfurt (Oder)"
    assert extract_residence_city("Ich wohne in neustadt an der weinstraße.") == "Neustadt an der Weinstraße"
    assert extract_residence_city("Ich wohne in Neustadt an der Weinstraße.") == "Neustadt an der Weinstraße"
    assert extract_residence_city("Ich wohne in Weiden in der Oberpfalz.") == "Weiden in der Oberpfalz"
    assert extract_residence_city("Ich wohne in Weil am Rhein.") == "Weil am Rhein"
    assert extract_residence_city("Ich wohne in Neustadt bei Coburg.") == "Neustadt bei Coburg"
    assert extract_residence_city("Ich wohne in Buchholz in der Nordheide.") == "Buchholz in der Nordheide"
    assert extract_residence_city("Ich wohne in Freiburg im Breisgau.") == "Freiburg im Breisgau"
    assert extract_residence_city("Ich wohne in Freiberg am Neckar.") == "Freiberg am Neckar"
    assert extract_residence_city("Ich wohne in Burg auf Fehmarn.") == "Burg auf Fehmarn"
    assert extract_residence_city("Ich wohne in Dillingen an der Donau.") == "Dillingen an der Donau"
    assert extract_residence_city("Ich wohne in Neumarkt in der Oberpfalz.") == "Neumarkt in der Oberpfalz"
    assert extract_residence_city("Ich wohne in Mühlhausen/Thüringen.") == "Mühlhausen/Thüringen"
    assert extract_residence_city("Ich wohne in Schwedt/Oder.") == "Schwedt/Oder"
    assert extract_residence_city("Ich wohne in Wittstock/Dosse.") == "Wittstock/Dosse"


def test_extract_residence_city_does_not_split_stopword_prefixes() -> None:
    assert extract_residence_city("Ich wohne in St. Ingbert.") == "St. Ingbert"
    assert extract_residence_city("Ich wohne in Ingolstadt.") == "Ingolstadt"
    assert extract_residence_city("Ich wohne in Immenstadt.") == "Immenstadt"
    assert extract_residence_city("Ich wohne in Augsburg.") == "Augsburg"
    assert extract_residence_city("Ich wohne in Alsfeld.") == "Alsfeld"
    assert extract_residence_city("Ich wohne in Unterhaching.") == "Unterhaching"
    assert extract_residence_city("Ich wohne in Beilngries.") == "Beilngries"


def test_extract_residence_city_preserves_regional_compound_names() -> None:
    assert extract_residence_city("Ich wohne in Mülheim an der Ruhr.") == "Mülheim an der Ruhr"
    assert extract_residence_city("Ich wohne in Brandenburg an der Havel.") == "Brandenburg an der Havel"
    assert extract_residence_city("Ich wohne in Wörth am Rhein.") == "Wörth am Rhein"
    assert extract_residence_city("Ich wohne in Rüdesheim am Rhein.") == "Rüdesheim am Rhein"
    assert extract_residence_city("Ich wohne in St. Georgen im Schwarzwald.") == "St. Georgen im Schwarzwald"
    assert extract_residence_city("Ich wohne in Königstein im Taunus.") == "Königstein im Taunus"
    assert extract_residence_city("Ich wohne in Weiden in der Oberpfalz in der Musterstraße 5.") == "Weiden in der Oberpfalz"
    assert extract_residence_city("Ich wohne in Weil am Rhein in der Musterstraße 5.") == "Weil am Rhein"
    assert extract_residence_city("Ich wohne in Neustadt bei Coburg in der Musterstraße 5.") == "Neustadt bei Coburg"
    assert extract_residence_city("Ich wohne in Buchholz in der Nordheide in der Musterstraße 5.") == "Buchholz in der Nordheide"
    assert extract_residence_city("Ich wohne in Freiburg im Breisgau in der Musterstraße 5.") == "Freiburg im Breisgau"
    assert extract_residence_city("Ich wohne in Freiberg am Neckar in der Musterstraße 5.") == "Freiberg am Neckar"
    assert extract_residence_city("Ich wohne in Burg auf Fehmarn in der Musterstraße 5.") == "Burg auf Fehmarn"
    assert extract_residence_city("Ich wohne in Dillingen an der Donau in der Musterstraße 5.") == "Dillingen an der Donau"
    assert extract_residence_city("Ich wohne in Neumarkt in der Oberpfalz in der Musterstraße 5.") == "Neumarkt in der Oberpfalz"
    assert extract_residence_city("Ich wohne in Mühlhausen/Thüringen in der Musterstraße 5.") == "Mühlhausen/Thüringen"
    assert extract_residence_city("Ich wohne in Schwedt/Oder in der Musterstraße 5.") == "Schwedt/Oder"
    assert extract_residence_city("Ich wohne in Wittstock/Dosse in der Musterstraße 5.") == "Wittstock/Dosse"


def test_extract_residence_city_preserves_parenthetical_labels() -> None:
    assert extract_residence_city("Mein Wohnort ist Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Mein Wohnsitz liegt in Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Meine Adresse ist Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Meine Wohnanschrift lautet Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Halle (Saale) ist mein Wohnort.") == "Halle (Saale)"
    assert extract_residence_city("Ich habe meinen Wohnsitz in Halle (Saale).") == "Halle (Saale)"


def test_extract_residence_city_preserves_parenthetical_inverse_forms() -> None:
    assert extract_residence_city("Halle (Saale), dort wohne ich.") == "Halle (Saale)"
    assert extract_residence_city("In Halle (Saale) wohne ich.") == "Halle (Saale)"
    assert extract_residence_city("Halle (Saale) ist dort, wo ich wohne.") == "Halle (Saale)"
    assert extract_residence_city("Ich wohne, lebe in Halle (Saale).") == "Halle (Saale)"


def test_extract_residence_city_preserves_parenthetical_registration_and_bleibe_forms() -> None:
    assert extract_residence_city("Halle (Saale) bleibt meine Bleibe.") == "Halle (Saale)"
    assert extract_residence_city("Ich bin in Halle (Saale) gemeldet.") == "Halle (Saale)"
    assert extract_residence_city("Ich bin offiziell in Halle (Saale) ansässig.") == "Halle (Saale)"
    assert extract_residence_city("Ich habe in Halle (Saale) meinen Wohnsitz.") == "Halle (Saale)"
    assert extract_residence_city("Ich arbeite in Halle (Saale).") == ""
    assert extract_residence_city("Mein Geburtsort ist Halle (Saale).") == ""


def test_extract_residence_city_handles_unicode_label_initials() -> None:
    cases = {
        "Mein Wohnort ist Ålesund.": "Ålesund",
        "Meine Adresse ist Évry.": "Évry",
        "Čakovec ist mein Wohnort.": "Čakovec",
        "Mein Wohnsitz liegt in Žilina.": "Žilina",
        "Meine Wohnanschrift lautet Ørsta.": "Ørsta",
        "Ærøskøbing ist mein Zuhause.": "Ærøskøbing",
    }
    for text, expected in cases.items():
        assert extract_residence_city(text) == expected


def test_extract_residence_city_accepts_cities_starting_with_bin() -> None:
    assert extract_residence_city("Ich wohne in Binz.") == "Binz"
    assert extract_residence_city("Ich wohne in Bingen am Rhein.") == "Bingen"


def test_city_id_token_keeps_long_city_names_distinct() -> None:
    first = "A" * 49 + " Berlin"
    second = "A" * 49 + " Hamburg"
    first_token = _city_id_token(first)
    second_token = _city_id_token(second)

    assert first_token != second_token
    assert len(first_token) <= 48
    assert len(second_token) <= 48


def test_city_id_token_keeps_unicode_city_names_distinct() -> None:
    first_token = _city_id_token("Évry")
    second_token = _city_id_token("Vry")

    assert first_token != second_token
    assert first_token == _city_id_token("évry")
    assert len(first_token) <= 48


@pytest.mark.parametrize(
    "payload",
    (
        {"current_condition": [], "nearest_area": []},
        {"current_condition": [], "nearest_area": [{"areaName": [{"value": "Berlin"}]}]},
        {"current_condition": [{}], "nearest_area": []},
        [],
    ),
)
def test_fetch_weather_summary_handles_incomplete_provider_payload(payload) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("TeeBotus.runtime.weather_context.urllib.request.urlopen", return_value=Response()):
        assert fetch_weather_summary("Berlin") == "Berlin"


def test_extract_residence_city_accepts_activity_prefix_city_names() -> None:
    for city in ("Fahren", "Gehrden", "Reiskirchen", "Machern", "Sehnde", "Treffurt"):
        assert extract_residence_city(f"Ich wohne in {city}.") == city
    assert extract_residence_city("Ich wohne in Hamburg, weil ich arbeite.") == "Hamburg"


def test_extract_residence_city_ignores_owned_secondary_property() -> None:
    assert extract_residence_city("Ich wohne in Berlin und besitze ein Haus in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und besitze eine Wohnung in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und habe eine Wohnung in Hamburg.") == "Berlin"


def test_extract_residence_city_ignores_property_activity() -> None:
    for verb in ("vermiete", "verkaufe", "verwalte", "renoviere", "saniere", "nutze"):
        assert extract_residence_city(f"Ich wohne in Berlin und {verb} eine Wohnung in Hamburg.") == "Berlin"


def test_extract_residence_city_rejects_holiday_address_purpose() -> None:
    assert extract_residence_city("Meine Adresse in Berlin ist für meinen Urlaub.") == ""
    assert extract_residence_city("Meine Adresse in Berlin dient als Büro.") == ""
    assert extract_residence_city("Meine Adresse in Berlin ist für die Arbeit.") == ""
    assert extract_residence_city("Meine Adresse in Berlin ist die meines Arbeitgebers.") == ""
    assert extract_residence_city("Im Urlaub wohne ich in Berlin.") == ""
    assert extract_residence_city("In den Ferien lebe ich in Hamburg.") == ""
    assert extract_residence_city("Am Wochenende wohne ich in Berlin.") == ""
    assert extract_residence_city("Unter der Woche lebe ich in Hamburg.") == ""


def test_extract_residence_city_ignores_other_person_residence() -> None:
    assert extract_residence_city("Ich wohne in Berlin, meine Freundin wohnt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Eltern wohnen in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Freundin wohnt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Eltern wohnen in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg ist der Wohnort meiner Freundin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist der Wohnort meiner Eltern.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg ist der Wohnort meiner Firma.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist der Wohnort meines Arbeitgebers.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin sowie Hamburg ist der Wohnort meines Arbeitgebers.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, der Wohnort meines Arbeitgebers ist Hamburg.") == "Berlin"
    assert extract_residence_city("der Wohnort meines Arbeitgebers ist Hamburg; Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg gehört als Wohnort meiner Firma.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und der Wohnort von Frau Müller liegt bei Hamburg.") == "Berlin"
    assert extract_residence_city("Hamburg ist ihr Zuhause und Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg ist die Meldeadresse meines Arbeitgebers.") == "Berlin"
    assert extract_residence_city("die Meldeadresse meines Arbeitgebers ist Hamburg. Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Frau hat ihre Meldeadresse in Hamburg.") == "Berlin"
    assert extract_residence_city("meine Frau hat ihre Meldeadresse in Hamburg. Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Firma ist in Hamburg ansässig.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Frau ist wohnhaft in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Frau ist gemeldet in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Firma hat Hamburg als Adresse.") == "Berlin"
    for owner in ("von meiner Freundin", "der Freundin", "von meinen Eltern", "dem Arbeitgeber"):
        assert extract_residence_city(f"Ich wohne in Berlin, Hamburg ist der Wohnort {owner}.") == "Berlin"


def test_extract_residence_city_handles_short_self_clause_after_other_person() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Eltern wohnen in Hamburg, wir in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner ist in Hamburg, ich bei Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg und ich in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, aber ich in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Eltern wohnen in Hamburg, während wir in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Freundin in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg und du in Berlin.") == ""


def test_extract_residence_city_handles_label_first_short_self_clause() -> None:
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg und ich in Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse meines Partners liegt bei Hamburg, aber ich in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnsitz meiner Eltern ist Hamburg, wir in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg und du in Berlin.") == ""


def test_extract_residence_city_handles_colon_label_first_short_self_clause() -> None:
    assert extract_residence_city("Der Wohnort meiner Frau: Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort meiner Frau: Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse meiner Frau: Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnsitz meiner Eltern = Hamburg; wir in Berlin.") == "Berlin"


def test_extract_residence_city_handles_pronoun_first_short_self_clause() -> None:
    assert extract_residence_city("Ihr Wohnort ist Hamburg und ich in Berlin.") == "Berlin"
    assert extract_residence_city("Sein Wohnsitz: Hamburg, ich in Berlin.") == "Berlin"
    assert extract_residence_city("Deren Wohnadresse liegt bei Hamburg; wir in Berlin.") == "Berlin"
    assert extract_residence_city("Ihr Wohnort ist Hamburg und du in Berlin.") == ""


def test_extract_residence_city_handles_possessive_short_self_clause() -> None:
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg; meiner ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg, meine ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnsitz meiner Eltern ist Hamburg und unserer ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg; meiner liegt in Berlin.") == "Berlin"


def test_extract_residence_city_handles_by_owner_short_self_clause() -> None:
    assert extract_residence_city("Der Wohnort von meiner Frau ist Hamburg und ich in Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse von Frau Müller liegt bei Hamburg; wir in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnsitz von Herrn Meier: Hamburg, meiner ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort von Hamburg ist Berlin und ich in Potsdam.") == ""


def test_extract_residence_city_handles_sentence_boundary_short_self_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg. Ich in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg. Ich in Berlin.") == "Berlin"
    assert extract_residence_city("Ihr Wohnort ist Hamburg. Ich in Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau ist Hamburg. Meiner ist Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Mein Partner in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_self_first_short_person_clause() -> None:
    assert extract_residence_city("Ich in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich in Berlin und meine Freundin wohnt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich in Berlin; meine Eltern leben in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich in Berlin, mein Partner arbeitet in Hamburg.") == ""


def test_extract_residence_city_handles_colon_possessive_short_self_clause() -> None:
    assert extract_residence_city("Wohnort meiner Frau: Hamburg; meiner: Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnort meiner Frau: Hamburg; meine = Berlin.") == "Berlin"
    assert extract_residence_city("Der Wohnsitz meiner Eltern: Hamburg; unserer: Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort meiner Frau: Hamburg; deiner: Berlin.") == ""


def test_extract_residence_city_handles_qualified_short_self_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich derzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, ich aktuell in Berlin.") == "Berlin"
    assert extract_residence_city("Ihr Wohnort ist Hamburg. Ich momentan in Berlin.") == "Berlin"
    assert extract_residence_city("Ich gerade in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich beruflich in Berlin, mein Partner in Hamburg.") == ""


def test_extract_residence_city_handles_temporal_short_self_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich seit 2020 in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, ich seit Jahren in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Eltern wohnen in Hamburg, wir seit dem Studium in Berlin.") == "Berlin"
    assert extract_residence_city("Ich vorübergehend in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich beruflich seit 2020 in Berlin.") == ""


def test_extract_residence_city_handles_home_marker_short_self_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, bei mir in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, ich zu Hause in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich daheim in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, bei mir zuhause in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, bei mir daheim in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bei mir in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich arbeite bei mir in Berlin, mein Partner wohnt in Hamburg.") == ""


def test_extract_residence_city_handles_comma_home_marker_short_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, bei mir, in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, bei mir, bei Berlin.") == "Berlin"
    assert extract_residence_city("Meine Freundin lebt in Hamburg, ich zu Hause, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bei mir, in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich arbeite bei mir, in Berlin, mein Partner wohnt in Hamburg.") == ""


def test_extract_residence_city_handles_only_temporal_short_self_clause() -> None:
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich nur vorübergehend in Berlin.") == "Berlin"
    assert extract_residence_city("Ich nur vorübergehend in Berlin, mein Partner in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Partner wohnt in Hamburg, ich nur beruflich in Berlin.") == ""


def test_extract_residence_city_rejects_unknown_label_values() -> None:
    assert extract_residence_city("Mein Wohnort ist irgendwo.") == ""
    assert extract_residence_city("Mein Wohnort ist unklar.") == ""
    assert extract_residence_city("Mein Wohnort ist egal.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin.") == "Berlin"


def test_extract_residence_city_rejects_non_location_states() -> None:
    for value in ("überall", "ueberall", "wechselnd", "variabel", "flexibel", "offen", "mobil", "temporär"):
        assert extract_residence_city(f"Mein Wohnort ist {value}.") == ""


def test_extract_residence_city_rejects_continental_and_global_regions() -> None:
    for value in ("Ausland", "Europa", "Welt", "Afrika", "Asien"):
        assert extract_residence_city(f"Mein Wohnort ist {value}.") == ""
        assert extract_residence_city(f"Ich wohne in {value}.") == ""


def test_extract_residence_city_rejects_bare_region_placeholder() -> None:
    assert extract_residence_city("Ich wohne in der Region.") == ""
    assert extract_residence_city("Mein Wohnort ist Region.") == ""
    assert extract_residence_city("Ich wohne in der Region Berlin.") == "Berlin"


def test_extract_residence_city_handles_quoted_and_lautet_labels() -> None:
    cases = {
        'Mein Wohnort lautet: Berlin.': 'Berlin',
        'Mein Wohnort lautet „Hamburg“.': 'Hamburg',
        'Mein Wohnort ist "Berlin".': 'Berlin',
        "Mein Wohnort ist 'Hamburg'.": 'Hamburg',
        'Mein Wohnort ist (Potsdam).': 'Potsdam',
        'Wohnort: "Dresden".': 'Dresden',
    }
    for text, expected in cases.items():
        assert extract_residence_city(text) == expected


def test_extract_residence_city_rejects_naming_verb_fragments() -> None:
    assert extract_residence_city("Mein Wohnort heißt irgendwo.") == ""
    assert extract_residence_city("Mein Wohnort nennt sich unbekannt.") == ""
    assert extract_residence_city("Mein Wohnort heißt.") == ""
    assert extract_residence_city("Mein Wohnort heißt Berlin.") == "Berlin"


def test_extract_residence_city_rejects_modal_residence_claims() -> None:
    assert extract_residence_city("Mein Wohnort muss Berlin sein.") == ""
    assert extract_residence_city("Mein Wohnort ist Berlin.") == "Berlin"


def test_extract_residence_city_handles_quoted_compound_and_postal_values() -> None:
    assert extract_residence_city('Mein Wohnort ist "Halle (Saale)".') == "Halle (Saale)"
    assert extract_residence_city('Meine Adresse lautet "10115 Berlin".') == "Berlin"


def test_extract_residence_city_handles_compact_equals_labels() -> None:
    assert extract_residence_city("Mein Wohnort=„Bonn“.") == "Bonn"


def test_extract_residence_city_handles_question_answer_forms() -> None:
    assert extract_residence_city("Wo wohnst du? Berlin.") == "Berlin"
    assert extract_residence_city("Wo wohnst du: Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort? Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnort ist? Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnsitz? Dresden.") == "Dresden"
    assert extract_residence_city("Adresse? Bonn.") == "Bonn"
    assert extract_residence_city("Dein Wohnort: Bonn.") == "Bonn"
    assert extract_residence_city("Wo ist dein Wohnort? Berlin.") == "Berlin"
    assert extract_residence_city("Wo ist dein Zuhause? Berlin.") == "Berlin"
    assert extract_residence_city("Wo wohnst du eigentlich: in Hamburg.") == "Hamburg"
    assert extract_residence_city("Wo bist du wohnhaft? Berlin.") == "Berlin"
    assert extract_residence_city("Wo bist du ansässig? Hamburg.") == "Hamburg"
    assert extract_residence_city("Wo ist deine Wohnadresse? Bonn.") == "Bonn"
    assert extract_residence_city("Wo ist deine Meldeadresse? Potsdam.") == "Potsdam"
    assert extract_residence_city("Wo wohnst du? Berlin und Hamburg.") == ""
    assert extract_residence_city("Wo wohnst du? Berlin oder Potsdam.") == ""
    assert extract_residence_city("Wo wohnst du? Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Wohnst du in Hamburg?") == ""
    assert extract_residence_city("Wo wohnst du?") == ""
    assert extract_residence_city("Ist dein Wohnort Berlin?") == ""


def test_extract_residence_city_skips_label_fillers() -> None:
    assert extract_residence_city("Wohnort bitte: Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort aktuell Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort bitte.") == ""


def test_extract_residence_city_skips_registration_evidence_filler() -> None:
    assert extract_residence_city("Wohnort ist laut Meldeadresse Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort ist laut der Adresse Hamburg.") == "Hamburg"


def test_extract_residence_city_rejects_untrusted_label_filler() -> None:
    assert extract_residence_city("Wohnort ist laut Wikipedia Berlin.") == ""
    assert extract_residence_city("Wohnort ist laut User Berlin.") == ""
    assert extract_residence_city("Wohnort: derzeitig Berlin.") == "Berlin"


def test_extract_residence_city_rejects_bare_label_multiple_targets() -> None:
    assert extract_residence_city("Wohnort Berlin und Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Wohnort Berlin und arbeite in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_label_confidence_adverbs() -> None:
    assert extract_residence_city("Wohnort ist wahrscheinlich Berlin.") == ""
    assert extract_residence_city("Wohnort ist wohl Berlin.") == ""
    assert extract_residence_city("Wohnort ist sicher Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort: tatsächlich Berlin.") == "Berlin"
    assert extract_residence_city("Meine mögliche Wohnadresse ist Musterstraße 5, Berlin.") == ""
    assert extract_residence_city("Meine wahrscheinliche Wohnadresse ist Musterstraße 5, Berlin.") == ""
    assert extract_residence_city("Wohnadresse: Musterstr 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Hauptstr 7, Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen in Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin in Musterstraße 5, 10115 Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich lebe momentan in Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne aktuell bei Am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen Wohnsitz in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meine Bleibe in Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin wohnhaft in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin ansässig in Am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen festen Wohnsitz in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen offiziellen Wohnsitz in Musterstr. 5, Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe meine aktuelle Wohnadresse in Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen dauerhaften Wohnsitz in Am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin offiziell wohnhaft in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin dauerhaft ansässig in Hauptweg 7, Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_primary_residence_labels_with_street() -> None:
    assert extract_residence_city("Ich habe meinen Hauptwohnsitz in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen aktuellen Lebensmittelpunkt in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meinen festen Hauptwohnsitz in Hauptweg 7, Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_numbered_street_labels() -> None:
    assert extract_residence_city("Ich wohne in Musterstraße Nr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße Nr 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hauptweg Nr. 7a, Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_additional_street_types() -> None:
    assert extract_residence_city("Ich wohne in Musterdamm 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterkai 5, Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Musterdeich 5, Köln.") == "Köln"
    assert extract_residence_city("Ich wohne in Musterhöhe 5, Frankfurt.") == "Frankfurt"
    assert extract_residence_city("Ich wohne in Musterpark 5, München.") == "München"
    assert extract_residence_city("Ich wohne in Mustergürtel 5, Berlin.") == "Berlin"


def test_extract_residence_city_handles_international_postal_prefixes() -> None:
    assert extract_residence_city("Ich wohne in Musterstraße 5, D-10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5, DE-10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: D 10115 Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in D-10115 Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße 5, D-10115 Berlin; Meldeadresse Hamburg.") == ""


def test_extract_residence_city_handles_home_adverb_after_city() -> None:
    assert extract_residence_city("Ich wohne in Berlin zu Hause.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg zuhause.") == "Hamburg"
    assert extract_residence_city("Ich lebe in Köln daheim.") == "Köln"


def test_extract_residence_city_rejects_subject_as_home_city() -> None:
    assert extract_residence_city("Ich wohne in Berlin zu Hause.") != "Ich wohne"
    assert extract_residence_city("Wir leben in Hamburg daheim.") == "Hamburg"
    assert extract_residence_city("Wir sind in Hamburg daheim.") == "Hamburg"


def test_extract_residence_city_handles_status_after_residence_verb() -> None:
    assert extract_residence_city("Ich wohne in Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg ansässig.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Köln gemeldet.") == "Köln"
    assert extract_residence_city("Ich lebe in München registriert.") == "München"
    assert extract_residence_city("Ich bin amtlich in Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Ich bin in Hamburg offiziell gemeldet.") == "Hamburg"


def test_extract_residence_city_handles_comma_before_home_adverb() -> None:
    assert extract_residence_city("Ich wohne in Berlin, zu Hause.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg, zuhause.") == "Hamburg"
    assert extract_residence_city("Ich bin in Köln, daheim.") == "Köln"
    assert extract_residence_city("Wir sind in München, zu Hause.") == "München"


def test_extract_residence_city_handles_area_qualifier_before_street() -> None:
    assert extract_residence_city("Ich wohne im nördlichen Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne im Norden Berlins in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne im Bezirk Kreuzberg in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne im Stadtteil Altona in Hamburg an der Hauptstraße 7.") == "Hamburg"


def test_extract_residence_city_handles_labeled_area_qualifier_before_street() -> None:
    assert extract_residence_city("Mein Wohnort ist im nördlichen Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt im Norden Berlins in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse ist im Bezirk Kreuzberg in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnung liegt im Stadtteil Altona in Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Wohnhaft im nördlichen Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich bin wohnhaft im Norden Berlins in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meldeadresse: im Bezirk Kreuzberg in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city(
        "Meine Wohnadresse ist im Bezirk Kreuzberg in Berlin in der Musterstraße 5; "
        "Meldeadresse Hamburg."
    ) == ""


def test_extract_residence_city_handles_attributive_area_before_street() -> None:
    assert extract_residence_city("Ich wohne im Berliner Bezirk Kreuzberg in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse ist im Berliner Bezirk Kreuzberg in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnung liegt in der Berliner Innenstadt an der Hauptstraße 7.") == "Berlin"
    assert extract_residence_city("Wohnhaft im Berliner Zentrum in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich bin wohnhaft in der Innenstadt Berlins in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meldeadresse: im Hamburger Stadtteil Altona an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse ist in der Berliner Innenstadt in der Musterstraße 5; "
        "Meldeadresse Hamburg."
    ) == ""


def test_extract_residence_city_handles_house_number_words() -> None:
    assert extract_residence_city("Ich wohne in Musterstraße Nummer 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße Hausnummer 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße Hausnr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße Haus-Nr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Musterstraße Hs.-Nr. 5, Berlin.") == "Berlin"


def test_extract_residence_city_does_not_store_street_details_as_city() -> None:
    assert extract_residence_city("Ich wohne in Berlin in der Musterstraße 5, Hinterhaus.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg in der Hauptstraße 7, 2. OG links.") == "Hamburg"
    assert extract_residence_city("Meine Wohnadresse ist in Köln, Nebenweg 3, Wohnung B.") == "Köln"


def test_extract_residence_city_handles_postal_code_before_city() -> None:
    assert extract_residence_city("Ich wohne in 10115 Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist 50667 Köln in der Domstraße 3.") == "Köln"
    assert extract_residence_city("Wohnhaft in 20095 Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Meldeadresse: 01067 Dresden in der Hauptstraße 9.") == "Dresden"
    assert extract_residence_city(
        "Meine Wohnadresse ist 10115 Berlin in der Musterstraße 5; "
        "Meldeadresse 20095 Hamburg."
    ) == ""


def test_extract_residence_city_handles_postal_status_street_forms() -> None:
    assert extract_residence_city("Ich bin in 10115 Berlin in der Musterstraße 5 wohnhaft.") == "Berlin"
    assert extract_residence_city("Wohnhaft: 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich bin wohnhaft, 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnhaft 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city(
        "Ich bin in 10115 Berlin in der Musterstraße 5 wohnhaft; "
        "Meldeadresse 20095 Hamburg."
    ) == ""


def test_extract_residence_city_handles_country_address_prefixes() -> None:
    assert extract_residence_city("Ich wohne in Deutschland, 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in Deutschland, Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Deutschland, 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnhaft in Deutschland, 10115 Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich lebe in Österreich, 1010 Wien, Hauptstraße 7.") == "Wien"
    assert extract_residence_city("Meine Wohnadresse ist in der Schweiz, 8001 Zürich, Bahnhofstraße 2.") == "Zürich"
    assert extract_residence_city(
        "Meine Wohnadresse ist in Deutschland, 10115 Berlin, Musterstraße 5; "
        "Meldeadresse Hamburg."
    ) == ""


def test_extract_residence_city_handles_markt_street_type() -> None:
    assert extract_residence_city("Ich wohne am Markt 5 in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse ist am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Markt 7, Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_extended_street_types() -> None:
    for street_type in (
        "Wall", "Tor", "Brücke", "Bruecke", "Bogen", "Zeile", "Stein", "Winkel",
        "Kamp", "Koppel", "Dorf", "Feld", "Wiesen",
    ):
        assert extract_residence_city(f"Ich wohne am {street_type} 5 in Berlin.") == "Berlin"


def test_extract_residence_city_handles_comma_area_street_forms() -> None:
    assert extract_residence_city("Ich wohne im Bezirk Kreuzberg, Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Stadtteil Altona, Hamburg, Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Wohnadresse: im Bezirk Mitte, Berlin, Musterstraße 5.") == "Berlin"
    assert extract_residence_city(
        "Meine Wohnadresse ist im Bezirk Kreuzberg, Berlin, Musterstraße 5; "
        "Meldeadresse Hamburg."
    ) == ""


def test_extract_residence_city_handles_city_before_street_without_comma() -> None:
    assert extract_residence_city("Ich wohne in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin an der Musterstraße Nr. 5.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg in der Hauptstraße Hausnummer 7.") == "Hamburg"


def test_extract_residence_city_handles_labeled_city_before_street() -> None:
    assert extract_residence_city("Meine Wohnadresse ist in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnung liegt in Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Ich bin wohnhaft in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt in Frankfurt am Main in der Musterstraße 5.") == "Frankfurt am Main"


def test_extract_residence_city_handles_postposed_residence_status() -> None:
    assert extract_residence_city("Ich bin in Berlin in der Musterstraße 5 wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich bin in Hamburg, Hauptweg 7 ansässig.") == "Hamburg"
    assert extract_residence_city("Ich bin in Köln in der Musterstraße 5 gemeldet.") == "Köln"
    assert extract_residence_city("Ich bin in Frankfurt am Main in der Musterstraße 5 registriert.") == "Frankfurt am Main"


def test_extract_residence_city_handles_labeled_residence_status() -> None:
    assert extract_residence_city("Wohnhaft: Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ansässig in Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Gemeldet in Hauptweg 7, Hamburg.") == "Hamburg"
    assert extract_residence_city("Registriert: Hauptweg 7, Hamburg.") == "Hamburg"
    assert extract_residence_city("Offiziell wohnhaft: Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin aktuell wohnhaft: Musterstraße 5, Berlin.") == "Berlin"


def test_extract_residence_city_handles_status_city_before_street() -> None:
    assert extract_residence_city("Offiziell wohnhaft in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Aktuell wohnhaft in Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Wohnhaft in Frankfurt am Main in der Musterstraße 5.") == "Frankfurt am Main"
    assert extract_residence_city("Ich bin offiziell wohnhaft in Köln in der Hauptstraße 7.") == "Köln"


def test_extract_residence_city_handles_registered_city_before_street() -> None:
    assert extract_residence_city("Meine Meldeadresse ist in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Meldeanschrift liegt in Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Meine Privatadresse ist in Köln in der Musterstraße 5.") == "Köln"
    assert extract_residence_city("Meine Wohnadresse ist in Berlin in der Musterstraße 5, meine Meldeadresse ist Hamburg.") == ""


def test_extract_residence_city_handles_locality_type_before_street() -> None:
    assert extract_residence_city("Ich wohne in der Stadt Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne im Stadtgebiet von Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Ich lebe in der Gemeinde Köln in der Musterstraße 5.") == "Köln"
    assert extract_residence_city("Ich wohne in der Landeshauptstadt Berlin in der Musterstraße 5.") == "Berlin"


def test_extract_residence_city_handles_labeled_locality_type() -> None:
    assert extract_residence_city("Meine Wohnadresse ist in der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnung liegt im Stadtgebiet von Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Meine Meldeadresse ist in der Stadt Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Privatadresse liegt in der Gemeinde Köln.") == "Köln"


def test_extract_residence_city_handles_bare_city_before_street_label() -> None:
    assert extract_residence_city("Meldeadresse: in Berlin in der Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Privatadresse = in Köln in der Musterstraße 5.") == "Köln"
    assert extract_residence_city("Wohnadresse: in Berlin in der Musterstraße 5; Meldeadresse: in Hamburg in der Hauptstraße 7.") == ""


def test_extract_residence_city_handles_bare_locality_type_label() -> None:
    assert extract_residence_city("Meldeadresse: in der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: im Stadtgebiet von Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Privatadresse = in der Gemeinde Köln.") == "Köln"
    assert extract_residence_city("Wohnadresse: in der Stadt Berlin; Meldeadresse: in der Stadt Hamburg.") == ""


def test_extract_residence_city_handles_status_locality_type() -> None:
    assert extract_residence_city("Wohnhaft in der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin wohnhaft im Stadtgebiet von Hamburg an der Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Ansässig in der Gemeinde Köln.") == "Köln"
    assert extract_residence_city("Aktuell wohnhaft in der Landeshauptstadt Berlin in der Musterstraße 5.") == "Berlin"


def test_extract_residence_city_preserves_compound_city_before_street() -> None:
    assert extract_residence_city("Ich wohne in Brandenburg an der Havel in der Musterstraße 5.") == "Brandenburg an der Havel"
    assert extract_residence_city("Ich wohne in Frankfurt an der Oder in der Musterstraße 5.") == "Frankfurt an der Oder"
    assert extract_residence_city("Ich wohne in Mülheim an der Ruhr in der Musterstraße 5.") == "Mülheim an der Ruhr"
    assert extract_residence_city("Ich wohne in Neustadt an der Weinstraße in der Musterstraße 5.") == "Neustadt an der Weinstraße"


def test_extract_residence_city_preserves_compound_city_in_labeled_status() -> None:
    assert extract_residence_city("Mein Wohnsitz liegt in Frankfurt an der Oder in der Musterstraße 5.") == "Frankfurt an der Oder"
    assert extract_residence_city("Meine Wohnadresse ist in Mülheim an der Ruhr in der Musterstraße 5.") == "Mülheim an der Ruhr"
    assert extract_residence_city("Wohnhaft in Neustadt an der Weinstraße in der Musterstraße 5.") == "Neustadt an der Weinstraße"
    assert extract_residence_city("Meine Meldeadresse ist in Brandenburg an der Havel in der Musterstraße 5.") == "Brandenburg an der Havel"


def test_extract_residence_city_trims_trailing_evidence_filler() -> None:
    assert extract_residence_city("Wohnort: Berlin laut Meldeadresse.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin laut Profil.") == "Berlin"


def test_extract_residence_city_handles_direct_registration_labels() -> None:
    assert extract_residence_city("Gemeldet: Frankfurt.") == "Frankfurt"
    assert extract_residence_city("Registriert: Leipzig.") == "Leipzig"
    assert extract_residence_city("Aktuell gemeldet in Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher gemeldet in Berlin.") == ""


def test_extract_residence_city_rejects_punctuated_question_targets() -> None:
    assert extract_residence_city("Wo wohnst du? Berlin, Hamburg.") == ""
    assert extract_residence_city("Wo wohnst du? Berlin; Hamburg.") == ""
    assert extract_residence_city("Wo wohnst du? Berlin, Deutschland.") == "Berlin"


def test_extract_residence_city_rejects_other_person_residence_labels() -> None:
    assert extract_residence_city("Der Wohnort ist Berlin.") == ""
    assert extract_residence_city("Sein Wohnort ist Hamburg.") == ""
    assert extract_residence_city("Ihr Zuhause ist Potsdam.") == ""
    assert extract_residence_city("Deren Wohnsitz ist Dresden.") == ""
    assert extract_residence_city("Unser Wohnort ist Berlin.") == "Berlin"
    assert extract_residence_city("Dein Wohnort ist Hamburg.") == ""
    assert extract_residence_city("Dein Wohnort: Bonn.") == "Bonn"


def test_extract_residence_city_rejects_fixed_residence_negation_prefix() -> None:
    assert extract_residence_city("Kein fester Wohnort: Berlin.") == ""
    assert extract_residence_city("Keinen festen Wohnsitz: Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort: Potsdam.") == "Potsdam"


def test_extract_residence_city_rejects_future_confidence_prefixes() -> None:
    assert extract_residence_city("Wohnort ist voraussichtlich Berlin.") == ""
    assert extract_residence_city("Wohnort: voraussichtlich Berlin.") == ""
    assert extract_residence_city("Wohnort ist künftig Berlin.") == ""
    assert extract_residence_city("Wohnort: zukünftig Hamburg.") == ""
    assert extract_residence_city("Wohnort ist wieder Potsdam.") == "Potsdam"


def test_extract_residence_city_handles_explicit_answer_prefixes() -> None:
    assert extract_residence_city("Wo wohnst du? Antwort: Berlin.") == "Berlin"
    assert extract_residence_city("Wo wohnst du? Antwort ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Wo wohnst du? Antwort lautet: in Potsdam.") == "Potsdam"
    assert extract_residence_city("Wo wohnst du? Antwort: Berlin und Hamburg.") == ""


def test_extract_residence_city_rejects_unresolved_label_states() -> None:
    assert extract_residence_city("Wohnort ist momentan unklar.") == ""
    assert extract_residence_city("Wohnort ist aktuell unbekannt.") == ""
    assert extract_residence_city("Wohnort ist derzeit egal.") == ""
    assert extract_residence_city("Wohnort ist daheim.") == ""
    assert extract_residence_city("Wohnort ist aktuell Berlin.") == "Berlin"


def test_extract_residence_city_handles_negated_label_changes() -> None:
    assert extract_residence_city("Mein Wohnort ist keinesfalls Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist nie Berlin, aber jetzt Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort ist nicht Berlin, aber ich arbeite in Hamburg.") == ""


def test_extract_residence_city_handles_inverted_label_changes() -> None:
    assert extract_residence_city("Nicht mehr Berlin, jetzt Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Nicht länger Berlin, jetzt in Potsdam ist mein Wohnsitz.") == "Potsdam"


def test_extract_residence_city_rejects_temporal_suffix_claims() -> None:
    assert extract_residence_city("Wohnort Berlin ab morgen.") == ""
    assert extract_residence_city("Wohnort Berlin künftig.") == ""
    assert extract_residence_city("Wohnort Berlin früher.") == ""
    assert extract_residence_city("Wohnort Berlin ehemals.") == ""
    assert extract_residence_city("Wohnort Berlin seit heute.") == "Berlin"
    assert extract_residence_city("Wohnort Berlin ab sofort.") == "Berlin"


def test_extract_residence_city_handles_temporal_bare_labels() -> None:
    assert extract_residence_city("Mein Wohnort seit kurzem Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort seit heute Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnort: seit 2020 Potsdam.") == "Potsdam"
    assert extract_residence_city("Wohnort ab morgen Berlin.") == ""


def test_extract_residence_city_handles_expanded_location_questions() -> None:
    assert extract_residence_city("Wo genau wohnst du? Berlin.") == "Berlin"
    assert extract_residence_city("Wo genau lebst du? Hamburg.") == "Hamburg"
    assert extract_residence_city("Wo in Deutschland wohnst du? Potsdam.") == "Potsdam"
    assert extract_residence_city("In welcher Stadt wohnst du? Bonn.") == "Bonn"
    assert extract_residence_city("An welchem Ort lebst du? Dresden.") == "Dresden"
    assert extract_residence_city("Wo wohnst du denn? Leipzig.") == "Leipzig"
    assert extract_residence_city("In welcher Stadt wohnst du?") == ""


def test_extract_residence_city_handles_explicit_no_corrections() -> None:
    assert extract_residence_city("Nein, nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Nein: nicht in Berlin, sondern in Potsdam.") == "Potsdam"
    assert extract_residence_city("Nein, nicht Berlin, sondern ich arbeite in Hamburg.") == ""


def test_extract_residence_city_handles_short_clarification_marker() -> None:
    assert extract_residence_city("Wohnort ist Deutschland, genauer Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Deutschland, genauer Berlin.") == "Berlin"


def test_extract_residence_city_handles_inverse_origin_residence_labels() -> None:
    assert extract_residence_city("Berlin ist meine Heimat, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Geburtsort, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Geburtsort und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine frühere Heimat, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine ehemalige Geburtsstadt und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Herkunftsort, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimatstadt und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin war meine Heimat, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin war mein Geburtsort und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat sowie Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, aber Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Geburtsort, jedoch Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, dafür ist Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, stattdessen ist Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, während Hamburg mein Wohnort ist.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat, dort wohne ich nicht, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Ort meiner Geburt, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist ein Ort meiner Geburt und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Meine Heimat ist Berlin, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Mein Geburtsort ist Berlin und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Meine alte Heimat ist Berlin; Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat und in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Meine Heimat ist Berlin und in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Geburtsort, bei Hamburg gemeldet.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Heimat; Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Geburtsort; bei Hamburg gemeldet.") == "Hamburg"
    assert extract_residence_city("Ich bin in Berlin geboren, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Ich bin in Berlin geboren und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Ich bin in Berlin geboren und in Hamburg wohnhaft.") == "Hamburg"
    assert extract_residence_city("Ich wurde in Berlin geboren, bei Hamburg gemeldet.") == "Hamburg"
    assert extract_residence_city("Geburtsort: Berlin und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Geburtsort: Berlin, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Herkunftsort: Berlin; bei Hamburg gemeldet.") == "Hamburg"


def test_repeated_city_updates_deduplicate_duplicate_residence_memories(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=lambda city: f"{city}: 12 C",
    )
    rows = account_store.read_memory_entries(account_id)
    berlin = next(row for row in rows if row.get("id") == "mem_residence_city_berlin")
    account_store.write_memory_entries(account_id, rows + [dict(berlin)])

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, 1, tzinfo=timezone.utc),
        provider=lambda city: f"{city}: 13 C",
    )

    residence_rows = [
        row
        for row in account_store.read_memory_entries(account_id)
        if str(row.get("id") or "").startswith("mem_residence_city_")
    ]
    assert [row["id"] for row in residence_rows] == ["mem_residence_city_berlin"]


def test_extract_residence_city_keeps_current_clause_after_future_clause() -> None:
    assert extract_residence_city("Ab morgen wohne ich in Hamburg, derzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Ich werde bald in Hamburg wohnen, derzeit in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, ab morgen in Hamburg.") == "Berlin"


def test_extract_residence_city_keeps_current_state_before_history() -> None:
    assert extract_residence_city("Mein Wohnort ist Berlin, war aber früher Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt in Berlin, ehemals Hamburg.") == "Berlin"


def test_extract_residence_city_handles_immediate_and_planned_start() -> None:
    assert extract_residence_city("Ich wohne ab sofort in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne ab nächstem Jahr in Hamburg.") == ""
    assert extract_residence_city("Ich wohne ab morgen in Hamburg.") == ""


def test_extract_residence_city_reads_current_label_after_future_context() -> None:
    assert extract_residence_city("Mein künftiger Wohnort wird Hamburg, derzeit ist Berlin mein Wohnort.") == "Berlin"
    assert extract_residence_city("Derzeit ist Berlin mein Wohnort.") == "Berlin"
    assert extract_residence_city("Derzeit ist Berlin mein Arbeitsort.") == ""


def test_extract_residence_city_handles_direct_time_synonyms() -> None:
    assert extract_residence_city("Ich wohne im Moment in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe im Moment bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne gegenwärtig in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne derzeit noch in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne schon seit gestern in Berlin.") == "Berlin"


def test_extract_residence_city_handles_location_adverb_order() -> None:
    assert extract_residence_city("Mein Wohnsitz ist direkt in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt hier in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist dort in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne hier, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne dort, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin hier in Berlin daheim.") == "Berlin"


def test_extract_residence_city_handles_genitive_and_distance_relations() -> None:
    assert extract_residence_city("Ich wohne in Berlins Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Umgebung Berlins.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Gegend um Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne 20 km nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist 20 km nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt 5 km südlich Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt 5 km südlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist ungefähr 20 km nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt ca. 20 km nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt etwa 5,5 km südlich von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne ein paar Kilometer nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne wenige Kilometer südlich von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne um Berlin herum.") == "Berlin"
    assert extract_residence_city("Ich wohne außerhalb der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im nördlichen Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Münchens Umland.") == "München"


def test_extract_residence_city_handles_attributive_area_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist in Berlin-Nähe.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt in Berliner Nähe.") == "Berlin"
    assert extract_residence_city("Mein Wohnort befindet sich im Berliner Raum.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt in der Berliner Umgebung.") == "Berlin"


def test_extract_residence_city_handles_genitive_area_relations() -> None:
    for area in ("Stadtgebiet", "Stadtrand", "Stadtmitte", "Stadtzentrum", "Vorstadt", "Vorort", "Umland", "Raum"):
        assert extract_residence_city(f"Ich wohne in Berlins {area}.") == "Berlin"


def test_extract_residence_city_normalizes_postposed_area_suffixes() -> None:
    assert extract_residence_city("Mein Wohnort ist nicht in Berlin, sondern in Hamburg-Nähe.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort war in Berlin, jetzt in Hamburg Nähe.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist in Berlin, aber jetzt in Hamburg-Umgebung.") == "Hamburg"


def test_extract_residence_city_handles_current_attributive_area_changes() -> None:
    assert extract_residence_city("Mein Wohnort ist in Berlin, aber jetzt im Hamburger Raum.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist in Berlin, aber jetzt in der Hamburger Umgebung.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt im Hamburger Raum.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt in der Hamburger Umgebung.") == "Hamburg"


def test_extract_residence_city_normalizes_rund_um_herum() -> None:
    assert extract_residence_city("Mein Wohnort ist rund um München herum.") == "München"
    assert extract_residence_city("Ich lebe rund um München herum.") == "München"
    assert extract_residence_city("Ich wohne in Berlin, aber jetzt rund um München herum.") == "München"


def test_extract_residence_city_normalizes_irregular_city_adjectives() -> None:
    assert extract_residence_city("Mein Wohnort ist im Münchner Raum.") == "München"
    assert extract_residence_city("Mein Wohnort liegt in der Dresdner Umgebung.") == "Dresden"
    assert extract_residence_city("Mein Wohnort ist in Bremer Nähe.") == "Bremen"


def test_extract_residence_city_handles_direct_adjectival_rand() -> None:
    assert extract_residence_city("Ich lebe am Münchner Rand.") == "München"
    assert extract_residence_city("Ich wohne am Berliner Rand.") == "Berlin"


def test_extract_residence_city_handles_adjectival_vorstadt_relations() -> None:
    assert extract_residence_city("Ich wohne in der Münchner Vorstadt.") == "München"
    assert extract_residence_city("Mein Wohnort ist in einem Münchner Vorort.") == "München"
    assert extract_residence_city("Mein Wohnort liegt in Münchens Vorort.") == "München"
    assert extract_residence_city("Ich lebe in einem Vorort von München.") == "München"
    assert extract_residence_city("Mein Wohnort ist in Berliner Vorstadt.") == "Berlin"
    assert extract_residence_city("Ich wohne im Münchner Raum.") == "München"
    assert extract_residence_city("Ich wohne im Münchner Raum. Morgen besuche ich Berlin.") == "München"
    assert extract_residence_city("Ich wohne im Münchner Gebiet.") == "München"


def test_extract_residence_city_keeps_current_after_historical_area() -> None:
    assert extract_residence_city("Mein Wohnort war im Münchner Zentrum. Jetzt bin ich in Berlin.") == "Berlin"
    assert extract_residence_city("Früher wohnte ich im Münchner Zentrum. Heute in Berlin.") == "Berlin"


def test_extract_residence_city_preserves_s_ending_city_names() -> None:
    for city in ("Paris", "Reims", "Worms", "Tours", "Cannes", "Lens"):
        assert extract_residence_city(f"Ich wohne im Zentrum {city}.") == city


def test_extract_residence_city_handles_labeled_gemeinde_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist in der Gemeinde München.") == "München"
    assert extract_residence_city("Mein Wohnort ist in einer Gemeinde nahe München.") == "München"
    assert extract_residence_city("Mein Wohnort ist in einer Gemeinde unweit von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in einer Gemeinde rund um Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_stadtmitte_relations() -> None:
    assert extract_residence_city("Ich wohne in der Münchner Stadtmitte.") == "München"
    assert extract_residence_city("Mein Wohnort ist in der Münchner Stadtmitte.") == "München"
    assert extract_residence_city("Ich lebe in der Stadtmitte Münchens.") == "München"
    assert extract_residence_city("Mein Wohnort liegt in der Stadtmitte von Berlin.") == "Berlin"


def test_extract_residence_city_handles_genitive_center_relations() -> None:
    assert extract_residence_city("Ich wohne im Zentrum Münchens.") == "München"
    assert extract_residence_city("Ich wohne in der Innenstadt Münchens.") == "München"
    assert extract_residence_city("Ich lebe in Münchens Zentrum.") == "München"
    assert extract_residence_city("Ich wohne in Münchens Innenstadt.") == "München"
    assert extract_residence_city("Ich lebe im Zentrum München.") == "München"


def test_extract_residence_city_handles_named_residence_clauses() -> None:
    assert extract_residence_city("Ich lebe in einer Stadt, die München heißt.") == "München"
    assert extract_residence_city("Mein Wohnort ist eine Stadt, die München heißt.") == "München"
    assert extract_residence_city("München nennt sich mein Wohnort.") == "München"
    assert extract_residence_city("Berlin wird mein Wohnort genannt.") == "Berlin"
    assert extract_residence_city("Hamburg wird unser Zuhause genannt.") == "Hamburg"
    assert extract_residence_city("Berlin wird mein Arbeitsort genannt.") == ""


def test_extract_residence_city_handles_lebensmittelpunkt_area_relations() -> None:
    assert extract_residence_city("Mein Lebensmittelpunkt liegt in der Münchner Region.") == "München"
    assert extract_residence_city("Mein Lebensmittelpunkt ist außerhalb der Stadt München.") == "München"


def test_extract_residence_city_rejects_region_names_as_cities() -> None:
    assert extract_residence_city("Ich wohne in Bayern.") == ""
    assert extract_residence_city("Mein Wohnort ist in Brandenburg.") == ""
    assert extract_residence_city("Ich wohne im Raum Bayern.") == ""
    assert extract_residence_city("Mein Wohnort ist in der Region Hessen.") == ""
    assert extract_residence_city("Ich wohne in Norddeutschland.") == ""
    assert extract_residence_city("Mein Wohnort liegt im Ruhrgebiet.") == ""


def test_extract_residence_city_handles_outside_city_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist außerhalb der Stadt München.") == "München"
    assert extract_residence_city("Mein Wohnort ist außerhalb der Stadt Münchens.") == "München"
    assert extract_residence_city("Ich wohne außerhalb Münchens.") == "München"
    assert extract_residence_city("Ich lebe außerhalb von Berlin.") == "Berlin"


def test_extract_residence_city_handles_direct_stadtrand_relations() -> None:
    assert extract_residence_city("Ich wohne am Stadtrand München.") == "München"
    assert extract_residence_city("Ich wohne am Stadtrand Münchens.") == "München"
    assert extract_residence_city("Mein Wohnort ist am Stadtrand München.") == "München"
    assert extract_residence_city("Mein Wohnort liegt am Stadtrand von Berlin.") == "Berlin"


def test_extract_residence_city_handles_stadtgebiet_relations() -> None:
    assert extract_residence_city("Ich wohne im Münchner Stadtgebiet.") == "München"
    assert extract_residence_city("Ich wohne im Stadtgebiet von München.") == "München"
    assert extract_residence_city("Mein Wohnort ist im Berliner Stadtgebiet.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im Stadtgebiet von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Stadtgebiet Münchens.") == "München"
    assert extract_residence_city("Mein Wohnort liegt im Stadtgebiet Berlins.") == "Berlin"


def test_extract_residence_city_handles_innerhalb_relations() -> None:
    assert extract_residence_city("Mein Wohnort befindet sich innerhalb des Stadtgebiets von München.") == "München"
    assert extract_residence_city("Mein Wohnort liegt innerhalb des Stadtgebiets von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne innerhalb des Stadtgebiets München.") == "München"
    assert extract_residence_city("Ich lebe innerhalb der Stadt München.") == "München"
    assert extract_residence_city("Mein Wohnort liegt innerhalb von München.") == "München"
    assert extract_residence_city("Mein Wohnort liegt innerhalb Berlins.") == "Berlin"


def test_extract_residence_city_handles_hyphenated_direction_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist nord-östlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt 20 km nord-östlich von Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne süd-westlich von Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im nord-östlichen Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im nord-östlichen Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Nord-Osten.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Nord-Osten Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im süd-westlichen Berlin.") == "Berlin"


def test_extract_residence_city_rejects_negated_or_modal_direction_claims() -> None:
    assert extract_residence_city("Ich lebe keineswegs westlich von Hamburg.") == ""
    assert extract_residence_city("Mein Wohnort könnte südlich von Berlin liegen.") == ""
    assert extract_residence_city("Mein Wohnort wäre nördlich von Berlin.") == ""
    assert extract_residence_city("Mein Wohnort sollte westlich von Leipzig sein.") == ""


def test_extract_residence_city_keeps_direction_before_activity_context() -> None:
    assert extract_residence_city("Mein Wohnort ist nördlich von Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt ungefähr 20 km nördlich von Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne nördlich von Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne ungefähr 20 km nördlich von Berlin und ich studiere in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_label_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist bei meinen Eltern in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist rund um Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nördlich von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist südlich Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlins Umgebung.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in der Umgebung Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in der Gegend um Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist um Berlin herum.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Umland.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist am Berliner Stadtrand.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in einer Stadt namens Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist bei meiner Arbeit in Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist außerhalb von Berlin.") == ""


def test_extract_residence_city_keeps_label_before_activity_context() -> None:
    assert extract_residence_city("Mein Wohnort ist in Berlin und ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und mein Studium ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin und ich besuche Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin und ich bin heute in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin und ich lebe in Hamburg.") == ""


def test_extract_residence_city_keeps_direct_residence_before_activity_context() -> None:
    assert extract_residence_city("Ich wohne in Berlin und ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin und mein Studium ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ich besuche Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ich bin heute in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ich lebe in Hamburg.") == ""


def test_extract_residence_city_keeps_home_label_before_activity_context() -> None:
    assert extract_residence_city("Mein Zuhause ist in Berlin und ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Daheim ist in Berlin und ich studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist in Berlin und ich lebe in Hamburg.") == ""


def test_extract_residence_city_keeps_companion_residence_before_activity_context() -> None:
    assert extract_residence_city("Ich wohne bei meinen Eltern in Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich lebe mit meiner Familie in Berlin und studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Wir wohnen bei unseren Eltern in Berlin und arbeiten in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist bei meinen Eltern in Berlin und meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist bei meinen Eltern in Berlin und ich arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne bei meiner Arbeit in Berlin und studiere in Hamburg.") == ""


def test_extract_residence_city_rejects_institutional_companion_context() -> None:
    assert extract_residence_city("Ich wohne bei meiner Schule in Berlin.") == ""
    assert extract_residence_city("Ich wohne bei meiner Universität in Berlin.") == ""
    assert extract_residence_city("Ich wohne bei meiner Klinik in Berlin.") == ""
    assert extract_residence_city("Ich wohne bei meiner Familie in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne mit meinem Partner in Berlin.") == "Berlin"


def test_extract_residence_city_handles_comma_companion_before_activity() -> None:
    assert extract_residence_city("Ich wohne bei meinen Eltern, in Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich lebe mit meiner Familie, in Berlin und studiere in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist bei meinen Eltern, in Berlin und meine Arbeit ist in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist bei meinen Eltern, in Berlin und ich arbeite in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_reversed_residence_phrasings() -> None:
    assert extract_residence_city("In Berlin bin ich wohnhaft.") == "Berlin"
    assert extract_residence_city("In Berlin bin ich ansässig.") == "Berlin"
    assert extract_residence_city("Gemeldet bin ich in Leipzig.") == "Leipzig"
    assert extract_residence_city("Registriert bin ich in Bonn.") == "Bonn"
    assert extract_residence_city("Beruflich gemeldet bin ich in Berlin.") == ""
    assert extract_residence_city("Dienstlich registriert bin ich in Hamburg.") == ""
    assert extract_residence_city("Wohnen tue ich in Berlin.") == "Berlin"
    assert extract_residence_city("In Hamburg leben tue ich.") == "Hamburg"
    assert extract_residence_city("Arbeiten tue ich in Berlin.") == ""
    assert extract_residence_city("Ich nenne Berlin meinen Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin nenne ich meinen Wohnort.") == "Berlin"
    assert extract_residence_city("Ich nenne Berlin meinen Wohnsitz.") == "Berlin"
    assert extract_residence_city("Berlin nenne ich meinen Wohnsitz.") == "Berlin"
    assert extract_residence_city("Ich nenne Berlin meinen Arbeitsort.") == ""


def test_extract_residence_city_normalizes_unweit_and_nahe_labels() -> None:
    assert extract_residence_city("Mein Wohnort ist unweit Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist unweit Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nahe Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nahe Paris.") == "Paris"


def test_extract_residence_city_normalizes_region_labels() -> None:
    assert extract_residence_city("Mein Wohnort ist in der Region Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im Großraum Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im Großraum von München.") == "München"
    assert extract_residence_city("Mein Wohnort befindet sich im Berliner Großraum.") == "Berlin"


def test_extract_residence_city_rejects_future_residence_markers() -> None:
    assert extract_residence_city("Demnächst wohne ich in Berlin.") == ""
    assert extract_residence_city("Ich wohne seit morgen in Berlin.") == ""
    assert extract_residence_city("Ich wohne künftig in Berlin.") == ""
    assert extract_residence_city("Mein künftiger Wohnort ist Berlin.") == ""
    assert extract_residence_city("Ab heute wohne ich in Berlin.") == "Berlin"
    assert extract_residence_city("Seit heute wohne ich in Berlin.") == "Berlin"


def test_extract_residence_city_rejects_historical_perfect_residence() -> None:
    assert extract_residence_city("Ich bin früher in Berlin wohnhaft gewesen.") == ""
    assert extract_residence_city("Ich bin in Berlin wohnhaft gewesen.") == ""
    assert extract_residence_city("Ich bin wohnhaft in Berlin gewesen.") == ""
    assert extract_residence_city("Ich bin in Berlin wohnhaft.") == "Berlin"


def test_extract_residence_city_handles_never_negation() -> None:
    assert extract_residence_city("Ich lebe nie in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nie bei meinen Eltern, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe nie in Berlin.") == ""


def test_extract_residence_city_handles_relative_place_sentences() -> None:
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne.") == "Berlin"
    assert extract_residence_city("Berlin ist die Stadt wo ich wohne.") == "Berlin"
    assert extract_residence_city("Berlin ist die Stadt wo ich lebe.") == "Berlin"
    assert extract_residence_city("Berlin ist dort, wo ich wohne.") == "Berlin"
    assert extract_residence_city("Hamburg ist da, wo ich lebe.") == "Hamburg"
    assert extract_residence_city("Berlin ist, wo ich wohne.") == "Berlin"
    assert extract_residence_city("Wo ich wohne, ist Berlin.") == "Berlin"
    assert extract_residence_city("Berlin ist, wo ich arbeite.") == ""
    assert extract_residence_city("Wo ich arbeite, ist Hamburg.") == ""
    assert extract_residence_city("Berlin ist der Platz, an dem ich wohne.") == "Berlin"
    assert extract_residence_city("Der Platz, an dem ich lebe, ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Hamburg ist der Platz, an dem ich arbeite.") == ""
    assert extract_residence_city("Berlin ist dort, wo ich arbeite.") == ""
    assert extract_residence_city("Berlin ist der Ort, an dem ich lebe.") == "Berlin"
    assert extract_residence_city("Der Ort, an dem ich wohne, ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Ort wo ich wohne ist Berlin.") == "Berlin"
    assert extract_residence_city("Da, wo ich wohne, ist Berlin.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Arbeitsort.") == ""


def test_extract_residence_city_handles_postposed_place_adverbs() -> None:
    assert extract_residence_city("Es ist Berlin, wo ich wohne.") == "Berlin"
    assert extract_residence_city("Berlin, wo ich wohne.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, dort.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin, hier.") == "Berlin"
    assert extract_residence_city("Hamburg, wo ich arbeite.") == ""


def test_extract_residence_city_handles_residence_relative_repeat() -> None:
    assert extract_residence_city("Ich wohne in Berlin, wo ich lebe.") == "Berlin"
    assert extract_residence_city("Wir leben in Hamburg, wo wir wohnen.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, wo ich arbeite.") == "Berlin"


def test_extract_residence_city_handles_labeled_residence_relative_repeat() -> None:
    assert extract_residence_city("Mein Wohnort ist in Berlin, wo ich lebe.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist in Berlin, wo ich lebe.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin, wo ich arbeite.") == "Berlin"


def test_extract_residence_city_handles_country_prefix_without_comma() -> None:
    assert extract_residence_city("Ich wohne in Deutschland in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in Österreich in Wien.") == "Wien"
    assert extract_residence_city("Ich wohne in der Schweiz in Zürich.") == "Zürich"
    assert extract_residence_city("Mein Wohnort ist in Deutschland bei Berlin.") == "Berlin"


def test_extract_residence_city_handles_region_prefix_before_target() -> None:
    assert extract_residence_city("Mein Wohnort ist in Brandenburg bei Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt in Bayern bei München.") == "München"
    assert extract_residence_city("Mein Wohnort ist im Bundesland Brandenburg bei Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Bundesland Bayern bei München.") == "München"
    assert extract_residence_city("Ich lebe in Brandenburg bei Berlin.") == "Berlin"


def test_extract_residence_city_handles_confidence_adverbs() -> None:
    assert extract_residence_city("Ich wohne sicher in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne wirklich in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne tatsächlich in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne vielleicht in Berlin.") == ""
    assert extract_residence_city("Ich wohne vermutlich in Berlin.") == ""
    assert extract_residence_city("Mein Wohnort ist angeblich Berlin.") == ""
    assert extract_residence_city("Ich wohne scheinbar in Berlin.") == ""
    assert extract_residence_city("Ich glaube, ich wohne in Berlin.") == ""
    assert extract_residence_city("Ich denke, ich lebe in Berlin.") == ""
    assert extract_residence_city("Ich vermute, mein Wohnort ist Berlin.") == ""
    assert extract_residence_city("Ich nehme an, ich wohne in Berlin.") == ""
    assert extract_residence_city("Soweit ich weiß, wohne ich in Berlin.") == ""
    assert extract_residence_city("Soweit ich weiss, wohne ich in Berlin.") == ""
    assert extract_residence_city("Es scheint, ich wohne in Berlin.") == ""
    assert extract_residence_city("Es scheint, dass ich in Berlin wohne.") == ""
    assert extract_residence_city("Nach meinem Wissen wohne ich in Berlin.") == ""
    assert extract_residence_city("Nach allem, was ich weiß, wohne ich in Berlin.") == ""
    assert extract_residence_city("Nach allem, was ich weiss, wohne ich in Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin, glaube ich.") == ""
    assert extract_residence_city("Ich wohne in Berlin, denke ich.") == ""
    assert extract_residence_city("Ich wohne in Berlin, vermute ich.") == ""
    assert extract_residence_city("Ich wohne in Berlin, nehme ich an.") == ""
    assert extract_residence_city("Ich wohne in Berlin, wirklich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, sicher.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, tatsächlich.") == "Berlin"


def test_extract_residence_city_handles_additional_location_adverbs() -> None:
    assert extract_residence_city("Ich wohne erst in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne immer in Berlin.") == "Berlin"


def test_extract_residence_city_handles_temporal_location_adverbs() -> None:
    assert extract_residence_city("Ich wohne bisher in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne bislang in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne vorerst in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne zeitweise in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern vorübergehend in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne jetzt nicht mehr in Berlin, sondern nur vorübergehend in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern dauerhaft in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern bis auf Weiteres in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern seit gestern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht mehr in Berlin, sondern ab sofort in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne fast in Berlin.") == ""
    assert extract_residence_city("Ich wohne beinahe in Berlin.") == ""


def test_extract_residence_city_handles_remaining_label_relations() -> None:
    assert extract_residence_city("Mein Wohnort liegt außerhalb der Stadt Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt am Berliner Rand.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist außerhalb von Berlin.") == ""


def test_extract_residence_city_handles_labeled_local_districts() -> None:
    assert extract_residence_city("Mein Wohnort ist im Berliner Stadtteil Prenzlauer Berg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Stadtteil Prenzlauer Berg in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne im Prenzlauer Berg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Kreuzberg in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Kreuzberg bei Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Kreuzberg (Berlin).") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Bezirk Mitte in Berlin.") == "Berlin"
    assert extract_residence_city("Mein Zuhause ist in der Altstadt von Dresden.") == "Dresden"
    assert extract_residence_city("Mein Wohnort ist im Viertel Altona in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist im Ortsteil Prenzlauer Berg.") == ""


def test_extract_residence_city_normalizes_known_hyphenated_districts() -> None:
    assert extract_residence_city("Ich wohne in Berlin-Mitte.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin-Kreuzberg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin-Neukölln.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin-Neukoelln.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg-Altona.") == "Hamburg"
    assert extract_residence_city("Ich wohne in München-Schwabing.") == "München"
    assert extract_residence_city("Mein Wohnort ist Köln-Deutz.") == "Köln"
    assert extract_residence_city("Ich wohne in Köln Ehrenfeld.") == "Köln"
    assert extract_residence_city("Ich wohne in Köln-Ehrenfeld.") == "Köln"
    assert extract_residence_city("Ich wohne in München Schwabing.") == "München"
    assert extract_residence_city("Ich wohne in Berlin (Deutschland).") == "Berlin"
    assert extract_residence_city("Ich wohne in Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Ich wohne in Berlin (Kreuzberg), Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse ist in Berlin (Mitte), Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg (Altona), Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Frankfurt am Main (Sachsenhausen), Musterstraße 5.") == "Frankfurt am Main"


def test_extract_residence_city_normalizes_parenthesized_area_street_addresses() -> None:
    assert extract_residence_city("Ich wohne im Bezirk Kreuzberg (Berlin), Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Viertel Altona (Hamburg), Hauptstraße 7.") == "Hamburg"
    assert extract_residence_city("Wohnhaft im Stadtteil Prenzlauer Berg (Berlin), Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnadresse: im Bezirk Mitte (Berlin), Musterstraße 5.") == "Berlin"


def test_extract_residence_city_ignores_parenthesized_street_details() -> None:
    assert extract_residence_city("Ich wohne in Musterstraße 5 (Hinterhaus), Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5 (2. OG links), Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Musterstraße 5 (Wohnung B), Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne im Bezirk Kreuzberg (Berlin), Musterstraße 5 (Hinterhaus).") == "Berlin"


def test_extract_residence_city_handles_comma_city_and_descriptive_streets() -> None:
    assert extract_residence_city("Ich wohne in Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Straße des 17. Juni 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Straße des 17. Juni 5, Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Frankfurt am Main, Hauptstr. 5.") == "Frankfurt am Main"


def test_extract_residence_city_preserves_parenthesized_compound_city() -> None:
    assert extract_residence_city("Ich wohne in Halle (Saale), Musterstraße 5.") == "Halle (Saale)"
    assert extract_residence_city("Wohnadresse: Halle (Saale), Musterstraße 5.") == "Halle (Saale)"
    assert extract_residence_city("Ich wohne in Musterstraße 5, Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Wohnhaft: Musterstraße 5, Halle (Saale).") == "Halle (Saale)"


def test_extract_residence_city_handles_labeled_city_before_street_abbreviations() -> None:
    assert extract_residence_city("Wohnadresse: Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Wohnort: Frankfurt am Main, Musterstr. 5.") == "Frankfurt am Main"
    assert extract_residence_city("Meldeadresse: Brandenburg an der Havel, Musterstr. 5.") == "Brandenburg an der Havel"


def test_extract_residence_city_handles_district_city_with_abbreviated_street() -> None:
    assert extract_residence_city("Ich wohne in Berlin (Mitte), Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Wohnhaft: Musterstr. 5, Berlin (Kreuzberg).") == "Berlin"


def test_extract_residence_city_handles_postal_and_status_address_variants() -> None:
    assert extract_residence_city("Ich wohne in 10115 Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Wohnadresse: 10115 Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Musterstr. 5 wohnhaft.") == "Berlin"
    assert extract_residence_city("Wohnsitz: Deutschland, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnsitz in Deutschland, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz ist in Deutschland, 10115 Berlin.") == "Berlin"


def test_extract_residence_city_handles_comma_genitive_area_addresses() -> None:
    assert extract_residence_city("Ich wohne im Bezirk Mitte Berlins, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Wohnadresse: im Bezirk Kreuzbergs, Musterstraße 5.") == "Berlin"
    assert extract_residence_city("Wohnort: im Bezirk Mitte Berlins, Musterstraße 5.") == "Berlin"


def test_extract_residence_city_keeps_city_before_street_with_area_suffix() -> None:
    assert extract_residence_city("Ich wohne in Berlin, Musterstr. 5 und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Musterstr. 5 und Umgebung von Hamburg.") == ""


def test_extract_residence_city_normalizes_city_adjective_area_addresses() -> None:
    assert extract_residence_city("Ich wohne in der Berliner Umgebung, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburger Region, Musterstraße 5.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Münchner Gegend, Musterstraße 5.") == "München"


def test_extract_residence_city_handles_country_status_label_separator() -> None:
    assert extract_residence_city("Wohnhaft: Österreich, Wien, Musterstr. 5.") == "Wien"
    assert extract_residence_city("Gemeldet: Schweiz, Zürich, Bahnhofstr. 3.") == "Zürich"
    assert extract_residence_city("Wohnhaft: Österreich, Wien, Musterstr. 5; Meldeadresse Hamburg.") == ""


def test_extract_residence_city_handles_current_status_and_city_change_street_forms() -> None:
    assert extract_residence_city("Ich bin jetzt in Berlin, Musterstr. 5 wohnhaft.") == "Berlin"
    assert extract_residence_city(
        "Ich wohne nicht mehr in Berlin, Musterstr. 5, sondern in Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich wohne nicht mehr in Berlin, Musterstr. 5, sondern in Hamburg, Hauptweg 7; "
        "Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_formulated_city_before_street_moves() -> None:
    assert extract_residence_city("Meine Wohnadresse wechselte von Berlin, Musterstr. 5 auf Hamburg, Hauptweg 7.") == "Hamburg"
    assert extract_residence_city("Meine Wohnadresse hat sich von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlagert.") == "Hamburg"
    assert extract_residence_city("Meine Wohnadresse wurde von Berlin, Musterstr. 5 auf Hamburg, Hauptweg 7 geändert.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 gezogen.") == "Hamburg"


def test_extract_residence_city_handles_additional_city_before_street_moves() -> None:
    assert extract_residence_city(
        "Meine Wohnadresse ist jetzt Hamburg, Hauptweg 7 statt Berlin, Musterstr. 5."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine alte Wohnadresse war Berlin, Musterstr. 5, meine neue ist Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse: vorher Berlin, Musterstr. 5, jetzt Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse geändert: Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7: neue Wohnadresse."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse ist jetzt Hamburg, Hauptweg 7 statt Berlin, Musterstr. 5; Meldeadresse München."
    ) == ""
    assert extract_residence_city(
        "Meine Arbeitsadresse ist jetzt Hamburg, Hauptweg 7 statt Berlin, Musterstr. 5."
    ) == ""
    assert extract_residence_city(
        "Meine Wohnadresse ist jetzt Hamburg, Hauptweg 7 statt Berlin, Musterstr. 5?"
    ) == ""


def test_extract_residence_city_does_not_split_compound_residence_labels() -> None:
    assert extract_residence_city("Wohnortwechsel: Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7.") == ""
    assert extract_residence_city("Wohnort: Hamburg.") == "Hamburg"


def test_extract_residence_city_handles_move_verbs_before_street_addresses() -> None:
    assert extract_residence_city(
        "Ich bin aus Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 umgezogen."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich zog von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Umzug von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7: neue Wohnadresse."
    ) == "Hamburg"
    assert extract_residence_city(
        "Von Berlin, Musterstr. 5 bin ich nach Hamburg, Hauptweg 7 gezogen."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich bin aus Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 umgezogen; Meldeadresse München."
    ) == ""
    assert extract_residence_city(
        "Ich bin aus Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 gefahren."
    ) == ""


def test_extract_residence_city_handles_current_city_first_address_moves() -> None:
    assert extract_residence_city(
        "Ich habe jetzt Hamburg, Hauptweg 7 als Wohnadresse statt Berlin, Musterstr. 5."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnanschrift hat sich geändert: Hamburg, Hauptweg 7, früher Berlin, Musterstr. 5."
    ) == "Hamburg"
    assert extract_residence_city(
        "Die Wohnadresse ist jetzt Hamburg, Hauptweg 7 und nicht mehr Berlin, Musterstr. 5."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich habe jetzt Hamburg, Hauptweg 7 als Arbeitsadresse statt Berlin, Musterstr. 5."
    ) == ""
    assert extract_residence_city(
        "Meine Wohnanschrift hat sich geändert: Hamburg, Hauptweg 7, früher Berlin, Musterstr. 5; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_postal_and_parenthesized_move_addresses() -> None:
    assert extract_residence_city(
        "Meine Wohnadresse wechselte von 10115 Berlin, Musterstr. 5 auf 20095 Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich bin von Berlin, Musterstraße 5 (Hinterhaus) nach Hamburg, Hauptstraße 7 (2. OG links) gezogen."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse wechselte von 10115 Berlin, Musterstr. 5 auf 20095 Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_allows_same_city_residence_and_registration() -> None:
    assert extract_residence_city(
        "Meine Wohnadresse ist Berlin, Musterstr. 5. Meine Meldeadresse ist auch Berlin, Hauptweg 7."
    ) == "Berlin"
    assert extract_residence_city(
        "Wohnadresse: Berlin, Musterstr. 5; Meldeadresse ist auch Berlin, Hauptweg 7."
    ) == "Berlin"


def test_extract_residence_city_handles_pronoun_address_changes() -> None:
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5. Jetzt ist sie Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5. Jetzt lautet sie Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Früher war meine Wohnadresse Berlin, Musterstr. 5, jetzt ist sie Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Zuvor war meine Wohnadresse Berlin, Musterstr. 5, nun ist sie Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5. Seitdem ist sie Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5, bleibt aber Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5; die ist jetzt Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5; nun ist diese Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse war Berlin, Musterstr. 5. Jetzt ist sie Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_city_before_residence_labels() -> None:
    assert extract_residence_city(
        "Berlin war meine alte Wohnadresse, Hamburg ist jetzt meine neue Wohnadresse."
    ) == "Hamburg"
    assert extract_residence_city(
        "Berlin war meine frühere Wohnanschrift; Hamburg ist nun meine aktuelle Wohnanschrift."
    ) == "Hamburg"
    assert extract_residence_city(
        "Berlin war meine alte Arbeitsadresse, Hamburg ist jetzt meine neue Arbeitsadresse."
    ) == ""
    assert extract_residence_city(
        "Berlin war meine alte Wohnadresse, Hamburg ist jetzt meine neue Wohnadresse; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_street_before_residence_labels() -> None:
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Wohnadresse; Hamburg, Hauptweg 7 ist jetzt meine neue."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine frühere Wohnadresse Berlin, Musterstr. 5 ist vorbei, jetzt Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Arbeitsadresse; Hamburg, Hauptweg 7 ist jetzt meine neue."
    ) == ""
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Wohnadresse; Hamburg, Hauptweg 7 ist jetzt meine neue; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_informal_street_first_moves() -> None:
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Wohnadresse, jetzt Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Berlin, Musterstr. 5 ist nicht mehr meine Wohnadresse, sondern Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Arbeitsadresse, jetzt Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Berlin, Musterstr. 5 war meine alte Wohnadresse, jetzt Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_colon_labelled_old_new_addresses() -> None:
    assert extract_residence_city(
        "Meine alte Wohnadresse: Berlin, Musterstr. 5. Meine neue: Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Alte Wohnadresse: Berlin, Musterstr. 5; Neue Wohnadresse: Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine alte Arbeitsadresse: Berlin, Musterstr. 5. Meine neue: Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Meine alte Wohnadresse: Berlin, Musterstr. 5. Meine neue: Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_inline_labelled_address_times() -> None:
    assert extract_residence_city(
        "Wohnadresse alt: Berlin, Musterstr. 5; Wohnadresse neu: Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse früher Berlin, Musterstr. 5, heute Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse Berlin, Musterstr. 5, jetzt Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse alt: Berlin, Musterstr. 5; Wohnadresse neu: Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_labelled_from_to_moves() -> None:
    assert extract_residence_city(
        "Wohnadresse von Berlin, Musterstr. 5 zu Hamburg, Hauptweg 7 geändert."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt."
    ) == "Hamburg"
    assert extract_residence_city(
        "Arbeitsadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt."
    ) == ""
    assert extract_residence_city(
        "Wohnadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_passive_and_nominal_moves() -> None:
    assert extract_residence_city(
        "Wohnadresse wurde von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt."
    ) == "Hamburg"
    assert extract_residence_city(
        "Die Wohnadresse wurde von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 geändert."
    ) == "Hamburg"
    assert extract_residence_city(
        "Der Umzug der Wohnadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 ist erfolgt."
    ) == "Hamburg"
    assert extract_residence_city(
        "Arbeitsadresse wurde von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt."
    ) == ""
    assert extract_residence_city(
        "Wohnadresse wurde von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 verlegt; Meldeadresse München."
    ) == ""


def test_extract_residence_city_handles_colon_separator_moves() -> None:
    assert extract_residence_city(
        "Wohnadresse: Berlin, Musterstr. 5 -> Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse: Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7."
    ) == "Hamburg"
    assert extract_residence_city(
        "Arbeitsadresse: Berlin, Musterstr. 5 -> Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Wohnadresse: Berlin, Musterstr. 5 -> Hamburg, Hauptweg 7; Meldeadresse München."
    ) == ""


def test_extract_residence_city_rejects_alternative_residence_targets() -> None:
    assert extract_residence_city(
        "Meine Wohnadresse ist entweder Berlin, Musterstr. 5 oder Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Wohnadresse: Berlin, Musterstr. 5? Oder Hamburg, Hauptweg 7?"
    ) == ""


def test_extract_residence_city_rejects_unfinished_street_moves() -> None:
    assert extract_residence_city(
        "Ich ziehe von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Ich ziehe gerade von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Ich bin von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 gezogen."
    ) == "Hamburg"


def test_extract_residence_city_rejects_planned_address_moves() -> None:
    assert extract_residence_city(
        "Ich plane, meine Wohnadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 zu verlegen."
    ) == ""
    assert extract_residence_city(
        "Ich beabsichtige, meine Wohnadresse von Berlin, Musterstr. 5 nach Hamburg, Hauptweg 7 zu verlegen."
    ) == ""
    assert extract_residence_city(
        "Ich wohne aktuell in Berlin, Musterstr. 5; ich plane den Umzug nach Hamburg, Hauptweg 7."
    ) == "Berlin"


def test_extract_residence_city_keeps_residence_before_visit_with_street() -> None:
    assert extract_residence_city(
        "Ich wohne in Berlin, Musterstr. 5 und besuche Hamburg, Hauptweg 7."
    ) == "Berlin"
    assert extract_residence_city(
        "Ich lebe in Frankfurt am Main, Hauptstraße 5 und besuche Köln, Ring 7."
    ) == "Frankfurt am Main"


def test_extract_residence_city_rejects_temporally_multiple_street_residences() -> None:
    assert extract_residence_city(
        "Ich wohne in Berlin, Musterstr. 5 und lebe zeitweise in Hamburg, Hauptweg 7."
    ) == ""
    assert extract_residence_city(
        "Ich wohne in Berlin, Musterstr. 5 und lebe abwechselnd in Hamburg, Hauptweg 7."
    ) == ""


def test_extract_residence_city_handles_main_home_label() -> None:
    assert extract_residence_city("Meine Hauptwohnung ist in Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city("Meine Hauptwohnung ist in Berlin, meine Zweitwohnung in Hamburg.") == "Berlin"
    assert extract_residence_city("Meine Hauptwohnung befindet sich in Berlin und die Zweitwohnung in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich habe eine Hauptwohnung in Berlin und eine Zweitwohnung in Hamburg.") == "Berlin"
    assert extract_residence_city(
        "Meine Hauptwohnung ist in Berlin, Musterstr. 5, meine Zweitwohnung in Hamburg, Hauptweg 7."
    ) == "Berlin"
    assert extract_residence_city("Meine Zweitwohnung ist in Hamburg, Hauptweg 7.") == ""
    assert extract_residence_city(
        "Meine Hauptwohnung befindet sich in Berlin, Musterstr. 5 und die Zweitwohnung in Hamburg, Hauptweg 7."
    ) == "Berlin"


def test_extract_residence_city_keeps_primary_home_with_secondary_residence() -> None:
    assert extract_residence_city("Ich wohne in Berlin, mein zweiter Wohnsitz ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Nebenwohnung ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, mein Wohnsitz ist Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und habe meinen Wohnsitz in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und habe meinen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Zweitwohnsitz und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist meine Ferienwohnung und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Zweitwohnsitz und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Zweitwohnsitz sowie Hamburg mein Wohnort.") == "Hamburg"


def test_extract_residence_city_rejects_secondary_residence_without_primary() -> None:
    assert extract_residence_city("Mein zweiter Wohnsitz ist Hamburg.") == ""
    assert extract_residence_city("Mein zweiter Wohnsitz liegt in Hamburg.") == ""
    assert extract_residence_city("Meine Nebenwohnung ist Hamburg.") == ""
    assert extract_residence_city("Ich bin in Hamburg nebenwohnsitzlich gemeldet.") == ""
    assert extract_residence_city("Ich bin in Hamburg als Zweitwohnsitz gemeldet.") == ""
    assert extract_residence_city("Ich bin in Hamburg als Nebenwohnsitz gemeldet.") == ""
    assert extract_residence_city("Ich bin in Hamburg als Ferienwohnsitz gemeldet.") == ""
    assert extract_residence_city("Mein Wohnort: Hamburg (Nebenwohnsitz).") == ""
    assert extract_residence_city("Hauptwohnsitz: Berlin; Zweitwohnsitz: Hamburg.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin (Hauptwohnsitz).") == "Berlin"
    assert extract_residence_city("Berlin (Hauptwohnsitz).") == "Berlin"
    assert extract_residence_city("Hauptwohnsitz Berlin, Zweitwohnsitz Hamburg.") == "Berlin"
    assert extract_residence_city("Hauptwohnsitz Berlin; Nebenwohnsitz Hamburg.") == "Berlin"
    assert extract_residence_city("Wohnsitz: Berlin; ehemaliger Wohnsitz: Hamburg.") == "Berlin"
    assert extract_residence_city("Berlin (Hauptwohnsitz), Hamburg (Zweitwohnsitz).") == "Berlin"
    assert extract_residence_city("Berlin (Hauptwohnsitz); Hamburg (Nebenwohnsitz).") == "Berlin"
    assert extract_residence_city("Berlin (Hauptwohnsitz), Hamburg (Wohnsitz).") == ""
    assert extract_residence_city("Berlin (Hauptwohnsitz) und Hamburg (Arbeitsort).") == "Berlin"
    assert extract_residence_city("Ich wohne in Hamburg, meine Hauptadresse ist Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin; Hamburg ist meine aktuelle Adresse.") == ""
    assert extract_residence_city("Ich wohne in Berlin und war gestern in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist mein Arbeitsort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Hauptadresse ist ebenfalls Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg ist meine Hauptadresse.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Wohnort, Hamburg ist meine Hauptadresse.") == ""
    assert extract_residence_city("Hamburg ist meine Hauptadresse, Berlin mein Wohnort.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort und Hamburg ist meine aktuelle Adresse.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort und Hamburg ist meine Meldeadresse.") == ""
    assert extract_residence_city("Hamburg ist meine offizielle Meldeadresse, Berlin mein Wohnort.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort, Berlin ist meine Meldeadresse.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort, Hamburg ist meine Wohnung.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort und Hamburg mein Zuhause.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort und Berlin mein Zuhause.") == "Berlin"


def test_extract_residence_city_handles_labeled_center_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist in der Berliner Innenstadt.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in der Innenstadt Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Zentrum.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Zentrum Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist am Rand Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist am Berliner Stadtrand.") == "Berlin"


def test_extract_residence_city_handles_implicit_same_city_aliases() -> None:
    assert extract_residence_city("Meine Meldeadresse ist in Berlin, mein Wohnort auch.") == "Berlin"
    assert extract_residence_city("Meine Meldeadresse ist in Berlin, mein Wohnort ebenfalls.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist ebenso Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Meldeadresse auch") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin, meine Meldeadresse ebenfalls") == "Berlin"
    assert extract_residence_city("Wohnort Berlin, Meldeadresse ebenfalls Berlin") == "Berlin"
    assert extract_residence_city("Meldeadresse Berlin, Wohnort ebenfalls Berlin") == "Berlin"
    assert extract_residence_city("Meldeadresse ist Berlin, Wohnort auch.") == "Berlin"
    assert extract_residence_city("Ich wohne auch in Berlin") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine Meldeadresse auch in Berlin") == "Berlin"
    assert extract_residence_city("Meine Meldeadresse ist in Berlin, mein Wohnort Hamburg.") == ""
    assert extract_residence_city("Wohnort auch.") == ""
    assert extract_residence_city("Mein Wohnort ist auch.") == ""
    assert extract_residence_city("Mein Wohnort Ebenso.") == ""
    assert extract_residence_city("Mein Wohnort Ebenfalls.") == ""
    assert extract_residence_city("Wohnort Auch.") == "Auch"


def test_extract_residence_city_rejects_distinct_residence_and_registration_status() -> None:
    assert extract_residence_city("Ich wohne bei Berlin und bin in Hamburg gemeldet.") == ""
    assert extract_residence_city("Ich wohne in Berlin, gemeldet bin ich in Hamburg.") == ""
    assert extract_residence_city("Wohne in Berlin, gemeldet in Hamburg.") == ""
    assert extract_residence_city("Gemeldet in Hamburg, wohne in Berlin.") == ""
    assert extract_residence_city("Offiziell gemeldet in Hamburg, wohne aber in Berlin.") == ""
    assert extract_residence_city("Ich bin in Hamburg gemeldet, wohne aber in Berlin.") == ""
    assert extract_residence_city("Ich wohne in Berlin, offiziell gemeldet bin ich in Hamburg.") == ""
    assert extract_residence_city("Gemeldet bin ich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Gemeldet bin ich: Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne bei Berlin und bin in Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Gemeldet in Berlin, wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, bin in Hamburg gemeldet.") == ""
    assert extract_residence_city("Ich wohne in Berlin, offiziell gemeldet in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, bei Hamburg gemeldet.") == ""
    assert extract_residence_city("Ich wohne in Berlin, meine offizielle Meldung ist Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, bin aber in Hamburg gemeldet.") == ""
    assert extract_residence_city("Ich wohne in Berlin und habe dort keinen Wohnsitz.") == ""
    assert extract_residence_city("Ich wohne in Berlin und habe dort keinen festen Wohnsitz.") == ""
    assert extract_residence_city("Ich wohne in Berlin, bin amtlich in Hamburg registriert.") == ""
    assert extract_residence_city("Ich wohne in Berlin und bei Hamburg bin ich gemeldet.") == ""


def test_extract_residence_city_handles_direct_residence_registration_label_pairs() -> None:
    assert extract_residence_city("Wohnort: Berlin; Meldeadresse: Hamburg.") == ""
    assert extract_residence_city("Meldeadresse: Hamburg; Wohnort: Berlin.") == ""
    assert extract_residence_city("Wohnort: Berlin; Meldeadresse: Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin, Meldeadresse: Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Berlin ist meine Meldeadresse.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin und Berlin ist mein Wohnsitz.") == "Berlin"


def test_extract_residence_city_handles_direct_residence_registration_aliases() -> None:
    for alias in ("auch", "ebenfalls", "ebenso", "gleichfalls"):
        assert extract_residence_city(f"Wohnort: Berlin, Meldeadresse {alias}.") == "Berlin"
        assert extract_residence_city(f"Meldeadresse: Berlin, Wohnort {alias}.") == "Berlin"
        assert extract_residence_city(f"Meine Meldeadresse: Berlin, mein Wohnort {alias}.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin, aber Meldeadresse: Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin, aber Meldeadresse: Hamburg.") == ""
    assert extract_residence_city("Wohnort: Berlin, Meldeadresse ebenfalls Hamburg.") == ""


def test_extract_residence_city_handles_genitive_residence_addresses() -> None:
    assert extract_residence_city("Die Adresse meines Wohnorts ist Berlin.") == "Berlin"
    assert extract_residence_city("Die Adresse unseres Wohnsitzes liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Wohnanschrift meines Hauptwohnsitzes befindet sich in Dresden.") == "Dresden"
    assert extract_residence_city("Die Adresse meiner Wohnung ist Berlin.") == "Berlin"
    assert extract_residence_city("Die Adresse meines Zuhauses ist Berlin.") == "Berlin"
    assert extract_residence_city("Der Ort meines Wohnsitzes ist Berlin.") == "Berlin"
    assert extract_residence_city("Die Adresse eines Wohnorts ist Berlin.") == ""
    assert extract_residence_city("Die Adresse meines Wohnorts ist Berlin, meine Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Die Adresse meines Wohnorts ist Berlin, die Adresse meiner Wohnung ist Hamburg.") == ""


def test_extract_residence_city_handles_same_city_reference_labels() -> None:
    assert extract_residence_city("Mein Wohnort ist Berlin und dort ist auch meine Meldeadresse.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und dort ist meine Meldeadresse.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und dort ist auch meine Meldeadresse in Hamburg.") == ""
    assert extract_residence_city("Ich wohne dort, wo meine Meldeadresse in Berlin ist.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und die Adresse meines Wohnorts ist ebenfalls Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin und die Adresse meines Wohnorts ist Hamburg.") == ""
    assert extract_residence_city("Ich wohne dort, wo meine Meldeadresse in Berlin ist. Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, wo mein Wohnsitz ist.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, wo sich mein Wohnsitz befindet.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin, wo mein Wohnsitz liegt.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin, wo sich mein Wohnsitz befindet.") == "Berlin"


def test_extract_residence_city_handles_inverted_relative_residence_references() -> None:
    assert extract_residence_city("Wo ich gemeldet bin, da wohne ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo ich offiziell gemeldet bin, da wohne ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo ich amtlich registriert bin, dort lebe ich: bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne dort, wo ich gemeldet bin, in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe da, wo ich registriert bin: bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne dort, wo ich meinen Wohnsitz habe: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo ich meinen Wohnsitz habe, da wohne ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo ich meinen offiziellen Wohnsitz habe, dort lebe ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo mein Wohnsitz ist, da wohne ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo mein offizieller Wohnsitz ist, da wohne ich: in Berlin.") == "Berlin"
    assert extract_residence_city("Wo ich registriert bin, dort lebe ich: bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe da, wo ich meinen Hauptwohnsitz habe: in Dresden.") == "Dresden"
    assert extract_residence_city("Wo ich gemeldet bin, da wohne ich: in Berlin, meine Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne.") == "Berlin"
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne, aber nicht mehr.") == ""
    assert extract_residence_city("Berlin ist der Ort, an dem ich lebe, doch nicht mehr.") == ""
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne, aber früher.") == ""
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne, aber früher war ich in Hamburg.") == "Berlin"
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne, aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Ort, an dem ich lebe, doch inzwischen bei Potsdam.") == "Potsdam"
    assert extract_residence_city("Berlin ist die Stadt, in der ich wohne, aber jetzt arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen und wohne jetzt in Köln.") == "Köln"
    assert extract_residence_city("Ich lebe nicht mehr in Berlin, sondern wohne jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Früher war ich in Berlin wohnhaft, heute in Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine alte Wohnanschrift war Berlin, die neue ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, jetzt Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber inzwischen Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, jetzt wohnhaft in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aktuell ansässig in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, jetzt arbeite ich in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, habe aber meinen Hauptwohnsitz in Hamburg.") == ""
    assert extract_residence_city("Wir leben bei Berlin, haben jedoch unseren Wohnsitz in Potsdam.") == ""
    assert extract_residence_city("Ich wohne in der Nähe von Berlin und inzwischen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nahe Berlin, aber aktuell in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in der Nähe von Berlin und inzwischen in Potsdam arbeite ich.") == "Berlin"


def test_extract_residence_city_handles_labeled_area_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist in der Region um Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in der Berliner Region.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in der Berliner Gegend.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Gebiet.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Gebiet von Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in Berlin und Umgebung.") == "Berlin"


def test_extract_residence_city_handles_direct_area_relations() -> None:
    assert extract_residence_city("Ich wohne in Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich lebe in Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Region um Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne in der Berliner Region.") == "Berlin"
    assert extract_residence_city("Ich wohne im Berliner Gebiet.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, manchmal in Hamburg.") == ""


def test_extract_residence_city_handles_labeled_direction_relations() -> None:
    assert extract_residence_city("Mein Wohnort ist im nördlichen Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Norden.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Norden Berlins.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im westlichen Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist im Berliner Westen.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist nordöstlich Berlins.") == "Berlin"


def test_extract_residence_city_handles_named_locality_types() -> None:
    assert extract_residence_city("Mein Wohnort liegt im Dorf Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort liegt im Ort Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist die Gemeinde Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist eine Gemeinde namens Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist in einer Gemeinde.") == ""


def test_extract_residence_city_handles_bare_residence_address_label() -> None:
    assert extract_residence_city("Wohnort: Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnsitz: Hauptweg 7, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse: Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Hauptweg 7, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse: Hauptweg 7, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse = Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse, Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5-7, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5/7, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5 b, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Hauptstr. 7, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnort: Musterstr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meine künftige Wohnadresse: Hauptweg 7, Hamburg.") == ""
    assert extract_residence_city("Meine zukünftige Wohnadresse ist Hauptweg 7, Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Am Markt 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Zur Alten Post 5, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Am Markt 5 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5, Hinterhaus, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstraße 5, 2. OG, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: Musterstraße 5, Wohnung 3, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, 2. OG links, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Wohnung 3 links, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Hinterhaus rechts, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, 1. Etage, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Souterrain, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Aufgang A, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Haus A, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Hinterhaus, 2. OG, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Haus A, 2. OG links, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Aufgang A, Wohnung 3, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5a-5b, Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse: Musterstr. 5a/5b, Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse ist Musterstraße 5, Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse lautet Musterstraße 5, 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Die Meldeadresse befindet sich in Musterstr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Die Anschrift lautet Musterstr. 5, Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnsitz liegt in Unter den Linden 5, Berlin.") == "Berlin"
    assert extract_residence_city(
        "Ich wohne nicht mehr in Musterstraße 5, Berlin, sondern in Hauptweg 7, Hamburg."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse wechselte von Musterstraße 5, Berlin auf Hauptweg 7, Hamburg."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich bin von Musterstraße 5, Berlin nach Hauptweg 7, Hamburg gezogen."
    ) == "Hamburg"
    assert extract_residence_city(
        "Wohnadresse: vorher Musterstraße 5, Berlin, jetzt Hauptweg 7, Hamburg."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine alte Wohnadresse war Musterstraße 5, Berlin, meine neue ist Hauptweg 7, Hamburg."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse hat sich von Musterstraße 5, Berlin nach Hauptweg 7, Hamburg geändert."
    ) == "Hamburg"
    assert extract_residence_city(
        "Mein Wohnort hat sich von Musterstraße 5, Berlin nach Hauptweg 7, Hamburg verlagert."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Adresse wurde von Musterstraße 5, Berlin auf Hauptweg 7, Hamburg geändert."
    ) == "Hamburg"
    assert extract_residence_city(
        "Meine Wohnadresse ist jetzt Hauptweg 7, Hamburg statt Musterstraße 5, Berlin."
    ) == "Hamburg"
    assert extract_residence_city(
        "Ich habe meine Wohnadresse von Musterstraße 5, Berlin auf Hauptweg 7, Hamburg geändert."
    ) == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin 10115.") == "Berlin"
    assert extract_residence_city("Wohnsitz: Berlin 10115.") == "Berlin"
    assert extract_residence_city("Wohnort: Berlin, Hamburg.") == ""


def test_extract_residence_city_rejects_multiple_home_targets() -> None:
    assert extract_residence_city("Mein Zuhause ist in Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich wohne werktags in Berlin und am Wochenende in Hamburg.") == ""
    assert extract_residence_city("Ich wohne wochentags in Berlin und am Wochenende in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin und Umgebung von Hamburg.") == ""
    assert extract_residence_city("Ich wohne hauptsächlich in Berlin, manchmal in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne primär in Berlin, manchmal in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne primaer in Berlin, manchmal in Hamburg.") == "Berlin"


def test_extract_residence_city_handles_direct_home_relationships() -> None:
    assert extract_residence_city("Ich nenne Berlin mein Zuhause.") == "Berlin"
    assert extract_residence_city("Berlin nenne ich mein Zuhause.") == "Berlin"
    assert extract_residence_city("Mein Zuhause nenne ich Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort nenne ich Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Arbeitsort nenne ich Berlin.") == ""
    assert extract_residence_city("Mein Zuhause Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Geburtsort ist Berlin, meine Arbeit Hamburg, mein Zuhause Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Wohnort ist Berlin, mein Zuhause Hamburg.") == ""
    assert extract_residence_city("Berlin, mein Wohnort.") == "Berlin"
    assert extract_residence_city("Hamburg, unser Zuhause.") == "Hamburg"
    assert extract_residence_city("Berlin, mein Arbeitsort.") == ""
    assert extract_residence_city("Ich habe Berlin als Wohnort.") == "Berlin"
    assert extract_residence_city("Ich habe jetzt Hamburg als Wohnort.") == "Hamburg"
    assert extract_residence_city("Ich habe nun Potsdam als Wohnsitz.") == "Potsdam"
    assert extract_residence_city("Ich habe Berlin als Geburtsort und Hamburg als Wohnort.") == "Hamburg"
    assert extract_residence_city("Geburtsstadt Berlin, Wohnort Hamburg.") == "Hamburg"
    assert extract_residence_city("Geburtsort: Berlin; Wohnort: Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnort: Hamburg; Geburtsort: Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort Hamburg, Geburtsort Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort Hamburg, meine Heimat Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort Deutschland, Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse Berlin; Wohnort Hamburg.") == ""
    assert extract_residence_city("Berlin ist mein Wohnort. Hamburg ist mein Wohnort.") == ""
    assert extract_residence_city("Berlin ist meine Wohnadresse. Hamburg ist mein Wohnort.") == ""
    assert extract_residence_city("Wohnadresse Berlin. Geburtsort Hamburg.") == "Berlin"
    assert extract_residence_city("Geburtsort Berlin. Wohnadresse Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnadresse Berlin. Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstraße 5, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse: Musterstraße 5, Berlin; Meldeanschrift Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstraße 5-7, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Unter den Linden 5, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstraße 5 Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstraße 5, Hinterhaus, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstr. 5, Hinterhaus, 2. OG, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstr. 5a-5b, Berlin; Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse ist Musterstraße 5, Berlin; die Meldeadresse ist Hamburg.") == ""
    assert extract_residence_city("Wohnadresse: Musterstraße 5, Berlin; Meldeadresse 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Aktuelle Wohnadresse Berlin.") == "Berlin"
    assert extract_residence_city("Offizielle Wohnadresse Berlin.") == "Berlin"
    assert extract_residence_city("Gemeldeter Wohnsitz Berlin.") == "Berlin"
    assert extract_residence_city("Offizielle Wohnadresse Berlin. Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse Berlin und Hamburg.") == ""
    assert extract_residence_city("Der Wohnsitz Berlin und Hamburg.") == ""
    assert extract_residence_city("Wohnadresse Berlin, Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse Berlin und meine Arbeitsadresse Hamburg.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse Berlin und meine Geburtsstadt Hamburg.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse Berlin, genauer gesagt Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine aktuelle Wohnadresse Berlin, genauer gesagt Hamburg.") == "Hamburg"
    assert extract_residence_city("Meldeadresse Berlin, konkret Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Wohnadresse: Berlin, genauer gesagt Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnadresse = Berlin, genauer gesagt Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnadresse Halle (Saale).") == "Halle (Saale)"
    assert extract_residence_city("Die Wohnadresse Berlin (Deutschland).") == "Berlin"
    assert extract_residence_city("Die Wohnadresse Halle (Saale). Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse Berlin (Deutschland), genauer gesagt Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Meldeanschrift Berlin. Wohnort Hamburg.") == ""
    assert extract_residence_city("Der Meldesitz Berlin. Wohnadresse Hamburg.") == ""
    assert extract_residence_city("Die Meldeanschrift Berlin. Arbeitsadresse Hamburg.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse ist Berlin, die Meldeadresse ist Hamburg.") == ""
    assert extract_residence_city("Der Wohnsitz ist Berlin, der Meldesitz ist Hamburg.") == ""
    assert extract_residence_city("Die aktuelle Wohnadresse ist Berlin, die aktuelle Meldeadresse ist Hamburg.") == ""
    assert extract_residence_city("Eine Wohnadresse ist Berlin, eine Meldeanschrift ist Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse ist Berlin, die Arbeitsadresse ist Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse ist Berlin, die Meldeanschrift ist Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe den Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe einen offiziellen Wohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe meine aktuelle Wohnadresse in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin und Hamburg.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Ich habe eine Arbeitsadresse in Berlin.") == ""
    assert extract_residence_city("Ich habe eine ehemalige Wohnadresse in Berlin.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin, meine Meldeadresse in Hamburg.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin, meine Meldeanschrift in Hamburg.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin, meine Arbeitsadresse in Hamburg.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in Berlin, meine Arbeitsadresse in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe eine Wohnadresse in 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe einen Wohnsitz in 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Wohnadresse 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Die Wohnadresse 10115 Berlin. Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Ich bin in 10115 Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Wohnadresse 10115 Berlin, genauer gesagt 20095 Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich habe eine Wohnadresse in 10115 Berlin, genauer gesagt in 20095 Hamburg.") == "Hamburg"
    assert extract_residence_city("Wohnadresse 10115 Berlin und 20095 Hamburg.") == ""
    assert extract_residence_city("Ich habe eine Wohnadresse in 10115 Berlin und 20095 Hamburg.") == ""
    assert extract_residence_city("Wohnadresse 10115 Berlin und Umgebung.") == "Berlin"
    assert extract_residence_city("Mein tatsächlicher Wohnsitz Berlin.") == "Berlin"
    assert extract_residence_city("Meine tatsächliche Wohnadresse Berlin.") == "Berlin"
    assert extract_residence_city("Mein dauerhafter Wohnsitz Berlin.") == "Berlin"
    assert extract_residence_city("Mein vorübergehender Wohnsitz Berlin.") == "Berlin"
    assert extract_residence_city("Mein momentaner Wohnsitz Berlin.") == "Berlin"
    assert extract_residence_city("Mein ehemaliger Wohnsitz Berlin.") == ""
    assert extract_residence_city("Mein künftiger Wohnsitz Berlin.") == ""
    assert extract_residence_city("Mein dauerhafter Wohnsitz Berlin. Meldeadresse Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber meine Meldeadresse ist Hamburg.") == ""
    assert extract_residence_city("Meine Wohnadresse ist Berlin, meine Meldeadresse ist Hamburg.") == ""
    assert extract_residence_city("Wohnort Berlin / Arbeitsort Hamburg.") == "Berlin"
    assert extract_residence_city("Hamburg ist mein Zuhause, aber Berlin ist mein Wohnort.") == ""
    assert extract_residence_city("Hamburg war mein Wohnort, jetzt Berlin mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin war mein Wohnort, aber Hamburg ist jetzt mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist Berlin, bleibt aber Hamburg.") == ""
    assert extract_residence_city("Ich wohne im Berliner Norden.") == "Berlin"
    assert extract_residence_city("Berlin wohne ich.") == "Berlin"
    assert extract_residence_city("Berlin wohne ich nicht.") == ""
    assert extract_residence_city("Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg mein Wohnort, Berlin meine Heimat.") == "Hamburg"
    assert extract_residence_city("Berlin mein Wohnort und Hamburg mein Arbeitsort.") == "Berlin"
    assert extract_residence_city("Berlin nicht, sondern Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Nicht Hamburg ist mein Wohnort, sondern Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg ist nicht mein Wohnort, sondern Berlin ist mein Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne nicht in Berlin, aber ich wohne in Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, Hamburg schon.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, Hamburg bleibt es.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, aber Hamburg ist es.") == "Hamburg"
    assert extract_residence_city("Berlin ist nicht mein Wohnort, aber Hamburg bleibt es.") == "Hamburg"
    assert extract_residence_city("Berlin nicht als Wohnort, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Berlin ist kein Wohnort von mir, Hamburg schon.") == "Hamburg"
    assert extract_residence_city("Berlin ist keinesfalls mein Wohnort, Hamburg schon.") == "Hamburg"
    assert extract_residence_city("Berlin ist niemals mein Wohnort, Hamburg schon.") == "Hamburg"
    assert extract_residence_city("Nicht Berlin, sondern Hamburg wohne ich.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, genau genommen in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin, beziehungsweise in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich arbeite in Berlin, obwohl ich in Hamburg wohne.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin, weil ich dort wohne.") == "Berlin"
    assert extract_residence_city("Ich studiere in Hamburg, da ich dort wohne.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin, wobei ich in Hamburg wohne.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin, während ich in Hamburg wohne.") == "Hamburg"
    assert extract_residence_city("Ich arbeite in Berlin, auch wenn ich in Hamburg wohne.") == "Hamburg"
    assert extract_residence_city("In Berlin arbeite ich und in Hamburg lebe ich.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz liegt in Hamburg, obwohl ich in Berlin arbeite.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz liegt in Hamburg, während ich in Berlin arbeite.") == "Hamburg"
    assert extract_residence_city("Berlin (Arbeitsort), Hamburg (Wohnort).") == "Hamburg"
    assert extract_residence_city("Hamburg (Wohnort), Berlin (Arbeitsort).") == "Hamburg"
    assert extract_residence_city("Berlin, daheim.") == "Berlin"
    assert extract_residence_city("Potsdam, zuhause.") == "Potsdam"
    assert extract_residence_city("Leipzig, zu Hause.") == "Leipzig"
    assert extract_residence_city("In Berlin zuhause.") == "Berlin"
    assert extract_residence_city("Berlin zuhause.") == "Berlin"
    assert extract_residence_city("Berlin daheim.") == "Berlin"
    assert extract_residence_city("Früher Hamburg, jetzt Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe mich von Hamburg nach Berlin umgemeldet.") == "Berlin"
    assert extract_residence_city("Ich wohne jetzt endgültig in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin inzwischen endgültig in Berlin wohnhaft.") == "Berlin"
    assert extract_residence_city("Mein Hauptwohnsitz ist von Hamburg nach Berlin umgezogen.") == "Berlin"
    assert extract_residence_city("Nach dem Umzug ist Berlin mein Wohnort.") == "Berlin"
    assert extract_residence_city("Mein Wohnort war Hamburg; jetzt ist er Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe in Hamburg, mein Lebensmittelpunkt ist Berlin.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Hamburg und mein Arbeitsort ist Berlin.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Arbeitsort, auch wenn Hamburg mein Wohnort ist.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Arbeitsort, trotzdem ist Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist eigentlich Hamburg, mein Geburtsort Berlin.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist gegenwärtig Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist künftig Hamburg.") == ""
    assert extract_residence_city("Hamburg ist mein momentaner Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg, mein aktueller Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist unser aktueller Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein hauptsächlicher Wohnort.") == "Hamburg"
    assert extract_residence_city("Am 1. Januar ist mein aktueller Wohnort Hamburg.") == ""
    assert extract_residence_city("Hamburg als Wohnort.") == "Hamburg"
    assert extract_residence_city("Als Wohnort Hamburg.") == "Hamburg"
    assert extract_residence_city("Als Wohnsitz Hamburg.") == "Hamburg"
    assert extract_residence_city("Hamburg als Hauptwohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg als Arbeitsort.") == ""
    assert extract_residence_city("Eigentlich Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Aktuell Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Derzeit Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Momentan Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Nächstes Jahr Hamburg ist mein Wohnort.") == ""
    assert extract_residence_city("Eigentlich ist mein Wohnort Hamburg.") == "Hamburg"
    assert extract_residence_city("Hamburg ist noch immer mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist gegenwärtig mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist vorläufig mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist dauerhaft mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist temporär mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist vorübergehend mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein vorübergehender Wohnort.") == "Berlin"
    assert extract_residence_city("Hamburg ist mein jetziges Zuhause.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein gemeldeter Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein offizieller Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein fester Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein tatsächlicher Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein privater Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist mein ehemaliger Wohnort.") == ""
    assert extract_residence_city("Hamburg ist der Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist der gemeldete Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg ist der offizielle Wohnsitz.") == "Hamburg"
    assert extract_residence_city("Hamburg ist ein fester Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg ist der Arbeitsort.") == ""
    assert extract_residence_city("Hamburg, das ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg, dort ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg, hier ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg, da ist mein Zuhause.") == "Hamburg"
    assert extract_residence_city("Hamburg, da ist mein Arbeitsort.") == ""
    assert extract_residence_city("Hamburg heißt mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg heisst mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg wird als mein Wohnort genannt.") == "Hamburg"
    assert extract_residence_city("Hamburg nennt man meinen Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg heißt mein Arbeitsort.") == ""
    assert extract_residence_city("Hamburg heißt mein aktueller Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg wird mein derzeitiger Wohnort genannt.") == "Hamburg"
    assert extract_residence_city("Hamburg nennt man meinen derzeitigen Wohnort.") == "Hamburg"
    assert extract_residence_city("Hamburg heißt mein früherer Wohnort.") == ""
    assert extract_residence_city("Hamburg ist meine Wohnadresse.") == "Hamburg"
    assert extract_residence_city("Meine Meldeadresse lautet Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse - Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse – Berlin.") == "Berlin"
    assert extract_residence_city("Meine offizielle Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine private Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine offizielle Meldeanschrift: Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe eine offizielle Meldeadresse in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin amtlich gemeldet.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin amtlich registriert.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin gemeldet, offiziell.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Meldeadresse, offiziell.") == "Berlin"
    assert extract_residence_city("Ich bin in Berlin registriert, amtlich.") == "Berlin"
    assert extract_residence_city("Meine Meldeadresse ist 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meine offizielle Meldeadresse ist 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Meldeadresse: 10115 Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin in 10115 Berlin gemeldet.") == "Berlin"
    assert extract_residence_city("Berlin ist meine gemeldete Adresse.") == "Berlin"
    assert extract_residence_city("Meine aktuelle Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine amtliche Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine neue Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine gemeldete Meldeadresse ist Berlin.") == "Berlin"
    assert extract_residence_city("Meine geschäftliche Adresse ist Berlin.") == ""
    assert extract_residence_city("Meldeadresse Berlin.") == "Berlin"
    assert extract_residence_city("Meine Wohnadresse ist Hamburg, meine Arbeitsadresse ist Berlin.") == ""
    assert extract_residence_city("Hamburg ist meine alte Wohnadresse, Berlin meine aktuelle Wohnadresse.") == "Berlin"
    assert extract_residence_city("Hamburg ist meine offizielle Meldeadresse.") == "Hamburg"
    assert extract_residence_city("Hamburg ist meine aktuelle Wohnanschrift.") == "Hamburg"
    assert extract_residence_city("Hamburg als Wohnadresse.") == "Hamburg"
    assert extract_residence_city("Als Meldeadresse Hamburg.") == "Hamburg"
    assert extract_residence_city("Hamburg ist meine Arbeitsadresse.") == ""
    assert extract_residence_city("Hamburg mein Wohnort?") == ""
    assert extract_residence_city("Hamburg ist mein Wohnort?") == ""
    assert extract_residence_city("Hamburg könnte mein Wohnort sein.") == ""
    assert extract_residence_city("Hamburg soll mein Wohnort sein.") == ""
    assert extract_residence_city("Hamburg wäre mein Wohnort.") == ""
    assert extract_residence_city("Vielleicht wohne ich in Hamburg.") == ""
    assert extract_residence_city("Voraussichtlich wohne ich in Hamburg.") == ""
    for marker in ("mutmaßlich", "mutmasslich", "theoretisch", "hypothetisch", "potenziell", "potentiell", "womöglich", "womoeglich"):
        assert extract_residence_city(f"{marker.capitalize()} wohne ich in Hamburg.") == ""
    assert extract_residence_city("Die Wohnadresse ist Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Meldeadresse lautet Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Anschrift befindet sich in Hamburg.") == "Hamburg"
    assert extract_residence_city("Die Adresse liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Der Wohnsitz ist Hamburg.") == ""
    assert extract_residence_city("Ich nenne Berlin meinen Arbeitsort.") == ""
    assert extract_residence_city("Ich bin in Berlin daheim.") == "Berlin"


def test_extract_residence_city_handles_temporal_label_forms() -> None:
    assert extract_residence_city("Mein Wohnort ist gegenwärtig Berlin.") == "Berlin"
    assert extract_residence_city("Hamburg wohne ich aktuell.") == "Hamburg"
    assert extract_residence_city("Hamburg lebe ich derzeit.") == "Hamburg"
    assert extract_residence_city("Hamburg wohnte ich früher.") == ""
    assert extract_residence_city("Wohnort: Hamburg, war vorher Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort: Hamburg, vorher war Berlin.") == "Hamburg"
    assert extract_residence_city("Mein aktueller Wohnort: Hamburg, vorher Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnort: Hamburg, zuvor Berlin.") == "Hamburg"
    assert extract_residence_city("Wohnadresse: Hamburg, zuvor Berlin.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort ist ab sofort Berlin.") == "Berlin"
    assert extract_residence_city("Ab sofort ist mein Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Mein künftiger Wohnort ist Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin. Mein zukünftiger Wohnort ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, meine alte Adresse ist in Hamburg.") == "Berlin"


def test_extract_residence_city_ignores_common_foreign_person_residence_labels() -> None:
    cases = (
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Frau.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Mannes.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Chefs.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Vorgesetzten.",
        "Ich wohne in Berlin und meine Frau wohnt in Hamburg.",
        "Ich wohne in Berlin und mein Mann wohnt in Hamburg.",
        "Ich wohne in Berlin und mein Chef wohnt in Hamburg.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Oma.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Opas.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Großeltern.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Cousine.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Lebensgefährten.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Kindes.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Nachbarn.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Therapeutin.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Arztes.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Firmen.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Unternehmens.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Betriebs.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meines Vereins.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Praxis.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Klinik.",
        "Ich wohne in Berlin, Hamburg ist der Wohnort meiner Universität.",
    )
    for text in cases:
        assert extract_residence_city(text) == "Berlin"
    assert extract_residence_city("Berlin ist der Wohnort meiner Frau und Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Wohnort meiner Frau sowie Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Wohnort meiner Frau, Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Wohnort meiner Frau, aber Hamburg mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist der Wohnort meiner Frau, doch Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin war früher mein Wohnort, Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin war früher mein Wohnort und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein ehemaliger Wohnort und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist künftig mein Wohnort, Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist vielleicht mein Wohnort, Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist möglicherweise mein Wohnort und Hamburg ist mein Wohnort.") == "Hamburg"
    assert extract_residence_city("Berlin ist mein Wohnort, Hamburg war früher mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort, Hamburg ist künftig mein Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort, Hamburg ist vielleicht mein Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber Hamburg ist vielleicht mein Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber Hamburg ist vermutlich mein Wohnort.") == "Berlin"
    assert extract_residence_city("Hamburg mag mein Wohnort sein.") == ""
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist das Zuhause meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist die Wohnadresse meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist die Meldeadresse meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist die Wohnung meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg wohnt meine Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg lebt meine Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg lebt meine Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg ist meine Frau zuhause.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg ist meine Frau wohnhaft.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau hat ihren Wohnsitz in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau hat ihre Wohnadresse bei Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau ist in Hamburg gemeldet.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau ist zuhause in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau hat ihr Zuhause in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und der Wohnsitz meiner Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und der Wohnort meiner Frau ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse meiner Frau lautet Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnung meines Mannes bleibt Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau hat Hamburg als Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau nennt Hamburg ihren Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau führt Hamburg als Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau führt Hamburg als ihren Wohnort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und meine Frau sieht Hamburg als ihr Zuhause.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihre Wohnung ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihr Wohnsitz ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihr Wohnort liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihrer Frau Wohnort ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Frau lebt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und eine Frau lebt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und seine Frau lebt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihre Frau lebt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und der Mann lebt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihr Mann wohnt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse der Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse einer Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse seiner Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse ihrer Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und ihre Wohnadresse liegt bei Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und sein Wohnsitz liegt bei Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin sowie die Wohnung meiner Frau ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und dessen Wohnort ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und die Wohnadresse von Frau Müller ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist der Wohnort von Frau Müller.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, der Wohnort ihrer Frau ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, der Wohnort von ihr ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, die Wohnadresse von Frau Müller ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin; die Wohnadresse von Frau Müller ist Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin während der Wohnort ihrer Frau liegt in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein Wohnort ist Berlin, die Wohnadresse von Frau Müller ist Hamburg.") == "Berlin"
    assert extract_residence_city("Berlin ist mein Wohnort; die Wohnadresse von Frau Müller ist Hamburg.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Wohnadresse, ihr Wohnsitz ist Hamburg.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Wohnadresse, Hamburg ist ihr Wohnort.") == "Berlin"
    assert extract_residence_city("Berlin ist meine Wohnadresse, Hamburg gehört als Wohnort meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg gehört als Wohnort meiner Frau.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, Hamburg gilt meiner Frau als Wohnort.") == "Berlin"
    assert extract_residence_city("ihr Wohnsitz ist Hamburg und Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("der Wohnort ihrer Frau liegt in Hamburg. Ich wohne in Berlin.") == "Berlin"
    assert extract_residence_city("Meine Frau lebt in Hamburg, während ich in Berlin wohne.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg studiere ich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber in Hamburg arbeite ich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, doch in Hamburg studiere ich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist mein Geburtsort.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist meine Heimatstadt.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg bin ich beruflich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg mache ich eine Ausbildung.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und in Hamburg fahre ich zur Arbeit.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist meine Arbeitsstelle.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist meine Dienststelle.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und Hamburg ist meine Schule.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber in Hamburg bin ich beruflich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, doch in Hamburg bin ich dienstlich.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und bin in Hamburg zu Besuch.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber ich bin in Hamburg auf Besuch.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin und lebe zeitweise bei meiner Frau in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber bei meiner Frau in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, derzeit bei meiner Frau in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin, aber gerade in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich lebe derzeit in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin gerade in Hamburg wohnhaft.") == "Hamburg"


def test_extract_residence_city_handles_have_primary_home_label() -> None:
    assert extract_residence_city("Ich habe eine Wohnung in Berlin, Musterstr. 5.") == "Berlin"
    assert extract_residence_city(
        "Ich habe meine Wohnung in Berlin, Musterstr. 5; meine Zweitwohnung in Hamburg, Hauptweg 7."
    ) == "Berlin"
    assert extract_residence_city("Ich habe eine Zweitwohnung in Hamburg, Hauptweg 7.") == ""
    assert extract_residence_city("Ich habe eine Ferienwohnung in Hamburg, Hauptweg 7.") == ""


def test_weather_context_stores_city_memory_and_rate_limits_checks(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 12 C, trocken"

    first = update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    second = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo nochmal.",
        now=datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
        provider=provider,
    )
    third = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo nach zwei Stunden.",
        now=datetime(2026, 6, 15, 11, 1, tzinfo=timezone.utc),
        provider=provider,
    )

    assert first.checked is True
    assert second.skipped_reason == "rate_limited"
    assert third.checked is True
    assert calls == ["Berlin", "Berlin"]
    state = account_store.read_agent_state(account_id)
    assert state["weather_context"]["city"] == "Berlin"
    assert "Berlin: 12 C" in weather_context_text(account_store, account_id)
    memories = account_store.read_memory_entries(account_id)
    assert any(entry.get("kind") == "biographical_fact" and "Berlin" in str(entry.get("user_text")) for entry in memories)


def test_weather_context_stores_clean_city_after_implicit_alias(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 12 C, trocken"

    result = update_city_and_weather_context(
        account_store,
        account_id,
        "Mein Wohnort ist ebenso Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )

    assert result.city == "Berlin"
    assert calls == ["Berlin"]
    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Berlin"


def test_city_memory_append_is_retried_after_transient_failure(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    original_append = account_store.append_structured_memory_entry
    attempts = 0

    def append_once_fails(write_account_id: str, entry: dict[str, object]) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("memory append failed")
        return original_append(write_account_id, entry)

    with patch.object(account_store, "append_structured_memory_entry", side_effect=append_once_fails):
        update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Berlin.",
            now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
            provider=lambda city: f"{city}: 12 C",
        )
        update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Berlin.",
            now=datetime(2026, 6, 15, 9, 1, tzinfo=timezone.utc),
            provider=lambda city: f"{city}: 12 C",
        )

    memories = [
        entry
        for entry in account_store.read_memory_entries(account_id)
        if entry.get("id") == "mem_residence_city_berlin"
    ]
    assert attempts == 2
    assert len(memories) == 1


def test_city_change_invalidates_weather_cache_and_checks_new_city(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 9 C"

    update_city_and_weather_context(account_store, account_id, "Ich wohne in Berlin.", now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc), provider=provider)
    result = update_city_and_weather_context(account_store, account_id, "Ich wohne in Potsdam.", now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc), provider=provider)

    assert result.checked is True
    assert result.skipped_reason == ""
    assert result.weather_text == "Potsdam: 9 C"
    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Potsdam"
    assert "Potsdam: 9 C" in weather_context_text(account_store, account_id)
    assert calls == ["Berlin", "Potsdam"]


def test_city_change_keeps_only_current_generated_residence_memory(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    provider = lambda city: f"{city}: 9 C"

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Potsdam.",
        now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
        provider=provider,
    )

    residence_memories = [
        entry
        for entry in account_store.read_memory_entries(account_id)
        if str(entry.get("id") or "").startswith("mem_residence_city_")
    ]
    assert [entry["id"] for entry in residence_memories] == ["mem_residence_city_potsdam"]
    selection = account_store.select_structured_memory(
        account_id,
        query_text="Wo ist mein Wohnort?",
        max_prompt_chars=10000,
        max_entry_chars=1000,
    )
    assert selection.selected_ids == ("mem_residence_city_potsdam",)


def test_city_change_rolls_back_residence_memory_when_new_append_fails(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    provider = lambda city: f"{city}: 9 C"
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    previous_index = account_store.read_memory_index(account_id)
    original_append = account_store.append_structured_memory_entry

    def fail_new_city(write_account_id: str, entry: dict[str, object], **kwargs: object) -> str:
        if str(entry.get("id") or "") == "mem_residence_city_potsdam":
            raise OSError("new residence memory failed")
        return original_append(write_account_id, entry, **kwargs)

    with patch.object(account_store, "append_structured_memory_entry", side_effect=fail_new_city):
        result = update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Potsdam.",
            now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
            provider=provider,
        )

    assert result.city == "Berlin"
    assert result.skipped_reason == "memory_error"
    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Berlin"
    assert [entry["id"] for entry in account_store.read_memory_entries(account_id)] == ["mem_residence_city_berlin"]
    assert account_store.read_memory_index(account_id) == previous_index


def test_repeated_current_city_cleans_preexisting_stale_residence_memory(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    provider = lambda city: f"{city}: 9 C"
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_residence_city_potsdam",
            "kind": "biographical_fact",
            "memory_type": "semantic",
            "importance": 4,
            "user_text": "User erwaehnt als Wohnstadt: Potsdam.",
            "bot_text": "Als Wohnort fuer Wetter- und Kontextchecks gemerkt.",
            "keywords": ["wohnort", "stadt", "potsdam"],
        },
    )

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
        provider=provider,
    )

    residence_ids = [
        entry["id"]
        for entry in account_store.read_memory_entries(account_id)
        if str(entry.get("id") or "").startswith("mem_residence_city_")
    ]
    assert residence_ids == ["mem_residence_city_berlin"]


def test_city_case_change_does_not_bypass_weather_rate_limit(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 9 C"

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    result = update_city_and_weather_context(
        account_store,
        account_id,
        "ich wohne in berlin.",
        now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
        provider=provider,
    )

    assert result.skipped_reason == "rate_limited"
    assert calls == ["Berlin"]
    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Berlin"


def test_repeated_city_mention_persists_city_updated_at_when_rate_limited(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    first_now = datetime(2026, 6, 15, 9, tzinfo=timezone.utc)
    second_now = datetime(2026, 6, 15, 10, tzinfo=timezone.utc)

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=first_now,
        provider=lambda city: f"{city}: 9 C",
    )
    result = update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne weiterhin in Berlin.",
        now=second_now,
        provider=lambda city: f"{city}: 9 C",
    )

    assert result.skipped_reason == "rate_limited"
    state = account_store.read_agent_state(account_id)["weather_context"]
    assert state["city_updated_at"] == second_now.isoformat(timespec="seconds")


def test_city_memory_is_not_duplicated_when_state_write_fails_after_append(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    original_write_agent_state = account_store.write_agent_state
    failed = False

    def fail_once(write_account_id: str, state: dict[str, object]) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("state write failed")
        original_write_agent_state(write_account_id, state)

    with patch.object(account_store, "write_agent_state", side_effect=fail_once):
        with pytest.raises(OSError, match="state write failed"):
            update_city_and_weather_context(
                account_store,
                account_id,
                "Ich wohne in Berlin.",
                now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
                provider=lambda city: f"{city}: 12 C",
            )
        update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Berlin.",
            now=datetime(2026, 6, 15, 9, 1, tzinfo=timezone.utc),
            provider=lambda city: f"{city}: 12 C",
        )

    city_memories = [
        entry
        for entry in account_store.read_memory_entries(account_id)
        if entry.get("kind") == "biographical_fact" and "Berlin" in str(entry.get("user_text"))
    ]
    assert len(city_memories) == 1
    assert city_memories[0]["id"] == "mem_residence_city_berlin"


def test_city_change_rolls_back_memory_when_weather_state_write_fails(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    provider = lambda city: f"{city}: 9 C"
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    original_write_agent_state = account_store.write_agent_state
    failed = False

    def fail_on_city_change(write_account_id: str, state: dict[str, object]) -> None:
        nonlocal failed
        weather_state = state.get("weather_context")
        if not failed and isinstance(weather_state, dict) and weather_state.get("city") == "Potsdam":
            failed = True
            raise OSError("weather state write failed")
        original_write_agent_state(write_account_id, state)

    with patch.object(account_store, "write_agent_state", side_effect=fail_on_city_change):
        with pytest.raises(OSError, match="weather state write failed"):
            update_city_and_weather_context(
                account_store,
                account_id,
                "Ich wohne in Potsdam.",
                now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
                provider=provider,
            )

    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Berlin"
    assert [
        entry["id"]
        for entry in account_store.read_memory_entries(account_id)
        if str(entry.get("id") or "").startswith("mem_residence_city_")
    ] == ["mem_residence_city_berlin"]


def test_city_change_rolls_back_state_when_weather_state_write_fails_after_persist(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    provider = lambda city: f"{city}: 9 C"
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=provider,
    )
    original_write_agent_state = account_store.write_agent_state
    failed = False

    def write_then_fail(write_account_id: str, state: dict[str, object]) -> None:
        nonlocal failed
        weather_state = state.get("weather_context")
        original_write_agent_state(write_account_id, state)
        if not failed and isinstance(weather_state, dict) and weather_state.get("city") == "Potsdam":
            failed = True
            raise OSError("weather state write failed after persist")

    with patch.object(account_store, "write_agent_state", side_effect=write_then_fail):
        with pytest.raises(OSError, match="weather state write failed after persist"):
            update_city_and_weather_context(
                account_store,
                account_id,
                "Ich wohne in Potsdam.",
                now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
                provider=provider,
            )

    assert account_store.read_agent_state(account_id)["weather_context"]["city"] == "Berlin"
    assert [
        entry["id"]
        for entry in account_store.read_memory_entries(account_id)
        if str(entry.get("id") or "").startswith("mem_residence_city_")
    ] == ["mem_residence_city_berlin"]


def test_city_memory_rollback_failure_is_not_hidden(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=lambda city: f"{city}: 9 C",
    )
    original_append = account_store.append_structured_memory_entry
    original_write_index = account_store.write_memory_index
    append_finished = False

    def append_then_fail(write_account_id: str, entry: dict[str, object], **kwargs: object) -> str:
        nonlocal append_finished
        memory_id = original_append(write_account_id, entry, **kwargs)
        append_finished = True
        raise OSError("residence append failed after persist")

    def fail_index_rollback(write_account_id: str, index: dict[str, object]) -> None:
        if append_finished:
            raise OSError("residence index rollback failed")
        original_write_index(write_account_id, index)

    with patch.object(account_store, "append_structured_memory_entry", side_effect=append_then_fail):
        with patch.object(account_store, "write_memory_index", side_effect=fail_index_rollback):
            with pytest.raises(RuntimeError, match="residence memory rollback failed"):
                update_city_and_weather_context(
                    account_store,
                    account_id,
                    "Ich wohne in Potsdam.",
                    now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
                    provider=lambda city: f"{city}: 9 C",
                )


def test_weather_provider_error_does_not_expose_stale_summary(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
        provider=lambda city: f"{city}: 12 C",
    )

    def failing_provider(_city: str) -> str:
        raise RuntimeError("offline")

    result = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo.",
        now=datetime(2026, 6, 15, 11, 1, tzinfo=timezone.utc),
        provider=failing_provider,
    )

    assert result.checked is True
    assert result.skipped_reason == "weather_error"
    assert weather_context_text(account_store, account_id) == ""
    weather_state = account_store.read_agent_state(account_id)["weather_context"]
    assert weather_state["summary"] == ""
    assert "offline" in weather_state["last_error"]


def test_weather_state_timestamps_use_supplied_now(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    first_now = datetime(2026, 6, 15, 9, 0, 0, tzinfo=timezone.utc)
    second_now = datetime(2026, 6, 15, 11, 1, 0, tzinfo=timezone.utc)

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=first_now,
        provider=lambda city: f"{city}: 12 C",
    )
    first_state = account_store.read_agent_state(account_id)["weather_context"]
    expected_first = first_now.isoformat(timespec="seconds")
    assert first_state["city_updated_at"] == expected_first
    assert first_state["last_checked_at"] == expected_first
    assert first_state["updated_at"] == expected_first

    def failing_provider(_city: str) -> str:
        raise RuntimeError("offline")

    update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo.",
        now=second_now,
        provider=failing_provider,
    )
    second_state = account_store.read_agent_state(account_id)["weather_context"]
    expected_second = second_now.isoformat(timespec="seconds")
    assert second_state["last_checked_at"] == expected_second
    assert second_state["updated_at"] == expected_second


def test_future_weather_check_timestamp_does_not_block_recheck(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        return f"{city}: 13 C"

    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
        provider=provider,
    )
    state = account_store.read_agent_state(account_id)
    state["weather_context"]["last_checked_at"] = "2026-06-15T15:00:00+00:00"
    account_store.write_agent_state(account_id, state)

    result = update_city_and_weather_context(
        account_store,
        account_id,
        "Hallo.",
        now=datetime(2026, 6, 15, 12, 1, tzinfo=timezone.utc),
        provider=provider,
    )

    assert result.checked is True
    assert result.skipped_reason == ""
    assert calls == ["Berlin", "Berlin"]


def test_parallel_weather_updates_share_one_rate_limited_check(tmp_path) -> None:
    account_store = store(tmp_path)
    _identity, account_id = prepare_account(account_store)
    calls: list[str] = []

    def provider(city: str) -> str:
        calls.append(city)
        time.sleep(0.05)
        return f"{city}: 12 C"

    def update() -> object:
        return update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Berlin.",
            now=datetime(2026, 6, 15, 9, tzinfo=timezone.utc),
            provider=provider,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: update(), range(2)))

    assert len(calls) == 1
    assert sorted(result.checked for result in results) == [False, True]


def test_engine_adds_cached_weather_context_to_openai_prompt(tmp_path, monkeypatch) -> None:
    account_store = store(tmp_path)
    identity, account_id = prepare_account(account_store)
    update_city_and_weather_context(
        account_store,
        account_id,
        "Ich wohne in Berlin.",
        now=datetime.now(timezone.utc),
        provider=lambda city: f"{city}: 18 C, leicht bewoelkt",
    )
    prompts: list[str] = []

    class Client:
        def create_reply(self, prompt, _instructions, previous_response_id=None):
            prompts.append(prompt)
            return type("Response", (), {"text": "Antwort", "response_id": "resp_weather"})()

    engine = TeeBotusEngine(
        account_store=account_store,
        instructions=BotInstructions(openai_enabled=True),
        openai_client=Client(),
    )

    actions = engine.process(event(identity, "Was soll ich heute machen?"))

    assert any(getattr(action, "text", "") == "Antwort" for action in actions)
    assert "Lokaler Wetterkontext:" in prompts[0]
    assert "Stadt/Wohnort: Berlin" in prompts[0]
    assert "18 C" in prompts[0]
