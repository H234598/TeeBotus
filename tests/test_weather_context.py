from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time
from unittest.mock import patch

import pytest

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.weather_context import extract_residence_city, update_city_and_weather_context, weather_context_text


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
    assert extract_residence_city("Mein Wohnort ist München.") == "München"
    assert extract_residence_city("Ich komme aus Hamburg, aber bin unterwegs.") == ""


def test_extract_residence_city_from_nearby_location_phrase() -> None:
    assert extract_residence_city("Ich wohne in der Nähe von Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe nahe Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in der Umgebung von Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe im Raum Leipzig.") == "Leipzig"
    assert extract_residence_city("Ich wohne unweit von Dresden.") == "Dresden"
    assert extract_residence_city("Ich wohne in der Stadt Berlin.") == "Berlin"


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
    assert extract_residence_city("Ich bin aktuell in Potsdam zuhause.") == "Potsdam"
    assert extract_residence_city("Ich bin seit kurzem in Leipzig zu Hause.") == "Leipzig"
    assert extract_residence_city("Seit 2024 bin ich in Köln zu Hause.") == "Köln"
    assert extract_residence_city("Ich bin hier in Potsdam zuhause.") == "Potsdam"
    assert extract_residence_city("Mein Zuhause ist Dresden.") == "Dresden"
    assert extract_residence_city("Zu Hause bin ich in Köln.") == "Köln"
    assert extract_residence_city("Ich bin bei meiner Freundin zuhause.") == ""


def test_extract_residence_city_after_person_or_household_phrase() -> None:
    assert extract_residence_city("Ich wohne bei meiner Freundin in Berlin.") == "Berlin"
    assert extract_residence_city("Ich lebe bei meinen Eltern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne aktuell bei meiner Freundin in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich lebe seit einiger Zeit bei meiner Freundin in Dresden.") == "Dresden"
    assert extract_residence_city("Seit 2024 wohne ich bei meinen Eltern in Bonn.") == "Bonn"
    assert extract_residence_city("Ich wohne direkt bei meiner Freundin in Köln.") == "Köln"


def test_extract_residence_city_from_plain_negated_change() -> None:
    assert extract_residence_city("Ich lebe nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht in Berlin, sondern in Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich wohne nicht in Berlin sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne nicht in Berlin.") == ""


def test_extract_residence_city_from_move_phrases() -> None:
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin umgezogen von Berlin nach Potsdam.") == "Potsdam"
    assert extract_residence_city("Ich bin nach Leipzig gezogen.") == "Leipzig"
    assert extract_residence_city("Ich bin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin aus Berlin nach Hamburg gezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich bin aus Berlin nach Hamburg umgezogen.") == "Hamburg"
    assert extract_residence_city("Ich zog von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gewechselt.") == "Hamburg"
    assert extract_residence_city("Ich bin von Berlin nach Hamburg weggezogen.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Wohnort von Berlin nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort wurde nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort änderte sich zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort änderte sich von Berlin zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort wechselte von Berlin nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz wechselte zu Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort verlegte sich nach Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort hat sich von Berlin nach Hamburg geändert.") == "Hamburg"
    assert extract_residence_city("Mein Wohnort hat sich nach Hamburg geändert.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Wohnort nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Ich werde nach Hamburg ziehen.") == ""


def test_extract_residence_city_from_wonen_leben_change() -> None:
    assert extract_residence_city("Ich wohne in Berlin, lebe aber jetzt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite jetzt in Hamburg.") == "Berlin"


def test_extract_residence_city_from_current_location_label() -> None:
    assert extract_residence_city("Mein aktueller Wohnort ist Berlin.") == "Berlin"
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
    assert extract_residence_city("Mein derzeitiger Wohnort: Leipzig.") == "Leipzig"
    assert extract_residence_city("Mein gegenwärtiger Ort ist Köln.") == "Köln"
    assert extract_residence_city("Heute ist mein Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Seit heute ist mein Wohnsitz Hamburg.") == "Hamburg"
    assert extract_residence_city("Nun ist mein Zuhause in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit 2020 ist mein Wohnort Berlin.") == "Berlin"
    assert extract_residence_city("Seit kurzem liegt mein Wohnsitz in Hamburg.") == "Hamburg"
    assert extract_residence_city("Seit einiger Zeit befindet sich mein Zuhause in Potsdam.") == "Potsdam"
    assert extract_residence_city("Seit zwei Jahren ist mein Hauptwohnsitz Dresden.") == "Dresden"
    assert extract_residence_city("Seit meiner Kindheit ist mein Wohnort Leipzig.") == "Leipzig"
    assert extract_residence_city("Seit 2020 ist mein Wohnort nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Seit 2020 ist mein Wohnort in Deutschland, genauer gesagt in Berlin.") == "Berlin"
    assert extract_residence_city("Heute ist mein Wohnsitz in der Schweiz, nämlich bei Zürich.") == "Zürich"
    assert extract_residence_city("Seit kurzem liegt mein Zuhause in Deutschland, konkret in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Wohnsitz liegt im Bundesland Sachsen, in Leipzig.") == "Leipzig"
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
    assert extract_residence_city("Ich bin seit 2020 in Bonn ansässig.") == "Bonn"
    assert extract_residence_city("Mein Zuhause bleibt in Köln.") == "Köln"
    assert extract_residence_city("Mein Zuhause ist weiterhin in Frankfurt.") == "Frankfurt"
    assert extract_residence_city("Mein Zuhause liegt nach wie vor in München.") == "München"
    assert extract_residence_city("Mein Zuhause ist nicht Berlin, sondern Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause befindet sich nicht in Berlin, sondern in Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Zuhause ist Berlin, aber jetzt Hamburg.") == "Hamburg"
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
    assert extract_residence_city("Ich wohne nicht in Berlin; aber arbeite jetzt in Hamburg.") == ""
    assert extract_residence_city("Ich wohne in Berlin, aber arbeite seit 2020 in Hamburg.") == "Berlin"
    assert extract_residence_city("Ich wohne zwar in Berlin, aber aktuell in Hamburg.") == "Hamburg"
    assert extract_residence_city("Ich wohne zwar in Berlin, aber arbeite aktuell in Hamburg.") == "Berlin"


def test_extract_residence_city_removes_daypart_context() -> None:
    assert extract_residence_city("Ich wohne in Hamburg nachts.") == "Hamburg"
    assert extract_residence_city("Ich wohne in Berlin schon seit Jahren.") == "Berlin"
    assert extract_residence_city("Ich wohne in Potsdam für zwei Jahre.") == "Potsdam"
    assert extract_residence_city("Ich wohne in Berlin während meines Studiums.") == "Berlin"
    assert extract_residence_city("Ich wohne in München zusammen mit meinen Eltern.") == "München"
    assert extract_residence_city("Ich wohne in Berlin in einer WG.") == "Berlin"
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
    assert extract_residence_city("Mein Hauptwohnsitz wurde nach Hamburg verlegt.") == "Hamburg"
    assert extract_residence_city("Ich habe meinen Hauptwohnsitz nach Potsdam verlegt.") == "Potsdam"
    assert extract_residence_city("Mein Lebensmittelpunkt: Berlin.") == "Berlin"
    assert extract_residence_city("Hauptwohnsitz: Hamburg.") == "Hamburg"
    assert extract_residence_city("Mein Hauptwohnsitz: Potsdam.") == "Potsdam"
    assert extract_residence_city("Mein Hauptwohnsitz ist dauerhaft in Bonn.") == "Bonn"
    assert extract_residence_city("Mein Wohnort ist dauerhaft Berlin.") == "Berlin"
    assert extract_residence_city("Ich wohne dauerhaft in Dresden.") == "Dresden"
    assert extract_residence_city("Ich habe meinen festen Wohnsitz in Köln.") == "Köln"
    assert extract_residence_city("Ich habe den Hauptwohnsitz in Berlin.") == "Berlin"
    assert extract_residence_city("Ich habe den Lebensmittelpunkt bei Hamburg.") == "Hamburg"
    assert extract_residence_city("Wir wohnen in Berlin.") == "Berlin"
    assert extract_residence_city("Wir leben seit zwei Jahren in Hamburg.") == "Hamburg"
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
    assert extract_residence_city("Ich wohne in Berlin, genauer gesagt in Hamburg.") == "Hamburg"
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
    assert extract_residence_city("Meine jetzige Wohnadresse liegt in Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine derzeitige Anschrift befindet sich in Potsdam.") == "Potsdam"
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
    assert extract_residence_city("Ich wohne rund um Berlin und arbeite in Hamburg.") == "Berlin"
    assert extract_residence_city("Mein damaliger Wohnort ist Dresden.") == ""
    assert extract_residence_city("Ich residiere in Berlin.") == "Berlin"
    assert extract_residence_city("Ich bin in Leipzig gemeldet.") == "Leipzig"
    assert extract_residence_city("Ich habe meine Bleibe in Hamburg.") == "Hamburg"
    assert extract_residence_city("Meine Bleibe ist in Potsdam.") == "Potsdam"
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
    assert extract_residence_city("Ich bin von Berlin nach Hamburg gezogen, wohne aber bei Köln.") == "Köln"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg auf Besuch.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg im Urlaub.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg zum Urlaub.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt in Hamburg als Tourist.") == "Berlin"
    assert extract_residence_city("Ich wohne in Berlin. Jetzt bei Freunden in Hamburg zu Besuch.") == "Berlin"


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
        update_city_and_weather_context(
            account_store,
            account_id,
            "Ich wohne in Potsdam.",
            now=datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc),
            provider=provider,
        )

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
