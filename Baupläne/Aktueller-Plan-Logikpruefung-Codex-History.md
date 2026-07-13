# Aktueller Bauplan: Logikpruefung Codex-History und Health-Status

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Bezug:** `Baupläne/Healthcheck-Applet-Plan.md`  
**Geltungsbereich:** Codex-History-Collector, SQL-Outbox, Dispatcher, `/status`, Healthcheck und TeeBotus-Cinnamon-Applet

## Ziel

Die Logik rund um Codex-History und Health-Status soll fachlich konsistent, idempotent und nachvollziehbar sein. Ein erfolgreicher Versand darf nicht erneut als Problem erscheinen; ein echter Fehler darf aber weder durch einen Fallback noch durch eine unklare Statusaggregation verschwinden. Bot, `/status`, Healthcheck und Applet sollen dieselbe Bedeutung der Statuswerte verwenden.

## Ausgangslage

- Die Health-Klassifikation ist versioniert (`classification_version=2`) und trennt handlungsrelevante Probleme von Hinweisen.
- Der `/status`-Pfad und das Applet beruecksichtigen die Bridge-Delegation fuer Codex-History.
- `latest` wird nach `created_at` bestimmt; Aenderungen an alten Eintraegen ueber `updated_at` verschieben nicht mehr die neueste Summary.
- Malformierte History-Zeilen werden als `problem_statuses=malformed:N` sichtbar gemacht.
- TBL zeigt aktuell `skipped=101` mit `skip_reasons=no_private_route:101`; die 101 Eintraege werden nicht still als gescheiterte Zustellungen behandelt.
- Der letzte Produktionsbestand hatte 1.467 History-Eintraege: 1.366 `accepted` und 101 `skipped`.
- Der aktuelle TeeBotus-Stand ist Version `1.9.377`, Commit `86796389`.

## Arbeitsprinzipien

1. **Sicherheit vor Komfort:** Keine automatische Datenloeschung, kein stilles Requeue und keine Secret-Ausgabe.
2. **Statussemantik explizit halten:** `accepted`, `delivered`, `acknowledged`, `failed`, `skipped` und `compacted` muessen einzeln nachvollziehbar bleiben.
3. **Idempotenz vor Wiederholung:** Ein bereits erfolgreich zugestelltes Ziel darf durch einen spaeteren, nicht zugeordneten Status nicht versehentlich erneut versendet werden.
4. **Delegation nicht mit Defekt verwechseln:** Eine Queue ohne private Route bleibt als begruendeter Skip sichtbar; delegierte Quellinstanzen werden nicht als fehlgeschlagen dargestellt.
5. **Rohdaten erhalten:** Jede Diagnose muss auf die konkrete History-Zeile, das Zielkonto, den Status und den Skip-Grund zurueckfuehrbar sein.

## Arbeitspakete

### 1. Dispatch-Status und Retry-Logik pruefen

- `TeeBotus/admin/codex_history.py` auf alle Statusuebergaenge und Aggregationen pruefen.
- Klaeren, ob `_successful_codex_history_dispatch_accounts()` absichtlich den letzten Status in der gespeicherten Reihenfolge verwendet oder ob Zeitstempel und Statusrang erforderlich sind.
- Verhalten fuer diese Sequenzen als Tests festlegen:
  - `accepted -> delivered -> acknowledged`: kein erneuter Versand.
  - `accepted -> failed`: kontrollierter Retry, sofern der Eintrag erneut dispatchbar ist.
  - `delivered -> failed`: kein Downgrade ohne expliziten neuen Versandversuch.
  - `skipped(no_private_route)`: kein Endlos-Retry ohne neue Route.
  - mehrere Konten: Erfolg eines Kontos darf den Zustand eines anderen Kontos nicht verdecken.
- Nur wenn die Sollsemantik belegt ist, die Aggregation korrigieren; keine pauschale Statusranglogik einbauen, die absichtliche neue Retry-Versuche blockiert.

### 2. Skip- und Fehlerursachen sauber trennen

- `no_private_route`, `compacted`, malformed und echte Zustellfehler getrennt ausweisen.
- Pruefen, ob `skipped` terminal, wiederaufnehmbar oder nur informativ ist.
- Fuer wiederaufnehmbare Eintraege eine explizite Admin-Aktion oder einen dokumentierten Requeue-Pfad vorsehen.
- Fuer nicht wiederaufnehmbare Eintraege Quarantaene/Auditspur statt stiller Entfernung verwenden.
- Keine Produktionsdaten veraendern, bevor die Ursache und das Zielverhalten getestet sind.

**Befund 2026-07-13:** Im separaten History-Dispatcher wurde `skipped` bisher in
`DispatcherStore.complete()` als `failed` behandelt und dadurch automatisch
requeued. Das widersprach der TeeBotus-Semantik fuer `no_private_route` und
konnte Endlos-Retries erzeugen.

**Umsetzung:** Der Dispatcher klassifiziert jetzt nach den persistierten
Empfaengerergebnissen:

- nur `skipped` -> terminal `skipped`
- erfolgreiche Zustellung plus `skipped` -> terminal `delivered`
- mindestens ein echter Fehler -> bisherige Retry-/Max-Attempts-Logik
- unbekannte Statuswerte -> echter Fehler, fail closed

Die Korrektur ist als History-Dispatcher `0.2.1` vorgesehen. Die Empfaenger-
Statuswerte werden nach dem Upsert erneut aus SQLite gelesen, damit bereits
vorhandene Empfaengerresultate bei der Gesamtklassifikation nicht verloren
gehen.

**Zweiter Befund 2026-07-13:** `history.append` speicherte einen gelieferten
Status korrekt, meldete im API-Ergebnis aber immer `queued`. Die Rueckgabe ist
jetzt der normalisierte, tatsaechlich gespeicherte Status.

**Dritter Befund 2026-07-13:** `dispatch.claim` persistierte den neuen
`updated_at`-Zeitpunkt, gab aber die alte Zeile aus dem SELECT zurueck. Die
Claim-Antwort setzt `updated_at` jetzt auf denselben Zeitpunkt wie die
persistierte `delivering`-Zeile.

**Vierter Befund 2026-07-13:** `complete()` loeschte das globale
`possible_duplicate`-Signal bei einem spaeteren erfolgreichen Retry, wenn nur
der aktuelle Empfaenger `false` meldete. Das verlor eine wichtige
Duplikatwarnung, obwohl der urspruengliche Empfaenger sie weiterhin trug.
Das Signal bleibt jetzt monoton erhalten und wird auch aus importierten
Empfaengerresultaten abgeleitet.

**Fuenfter Befund 2026-07-13:** `execute_delete()` pruefte die
Optimistic-Concurrency-Revision vor dem Schreib-Transaction-Lock. Eine
parallele Aenderung konnte dadurch zwischen Pruefung und Loeschung eintreten.
Die Revision wird jetzt innerhalb derselben `BEGIN IMMEDIATE`-Transaktion
erneut berechnet.

### 3. Ein einheitliches Statusmodell erzwingen

- Gemeinsame Statussemantik fuer:
  - SQL-Dispatch-Resultate
  - Dispatcher-Zusammenfassung
  - `TeeBotus/core/status.py`
  - Telegram-`/status`
  - Cinnamon-Applet
- Pruefen, dass `actionable_problem_statuses` nur echte Handlungsprobleme enthaelt.
- Sicherstellen, dass `queued=0` nur zusammen mit dem letzten Lauf, Fehlern, Skips und dem Alter der letzten erfolgreichen Verarbeitung bewertet wird.
- Fallbacks, optionale Provider und fehlende private Routen nicht als globalen Defekt melden.

### 4. Testabdeckung erweitern

- Unit-Tests fuer jede Statussequenz und jedes Zielkonto ergaenzen.
- Property-/Invariant-Tests fuer:
  - keine doppelte Zustellung nach terminalem Erfolg
  - kein Verlust eines Statusgrundes
  - stabile Latest-Auswahl nach `created_at`
  - malformed rows bleiben sichtbar
  - Bridge-Delegation bleibt konsistent
- Integrationsprobe mit einer isolierten SQL-Datenbank und synthetischer Outbox ausfuehren.
- Bestehende gezielte Suiten ausfuehren; keine kostenpflichtigen LLM- oder Provider-Calls fuer diese Logiktests.

### 5. Live-Nachweis und Applet-Abgleich

- `/status`, Healthcheck-JSON und Applet-Ausgabe fuer TBL, Bote der Wahrheit und Depressionsbot vergleichen.
- Nachweisen, dass die 101 `no_private_route`-Skips sichtbar, begruendet und nicht als gescheiterte Zustellungen gezaehlt werden.
- Applet aus dem Repository installieren und mit dem installierten Verzeichnis vergleichen.
- Erst nach erfolgreicher Probe entscheiden, ob die TBL-Skips repariert, neu geroutet oder bewusst als dauerhaft dokumentiert werden.

## Abschlusskriterien

Der Plan ist erst abgeschlossen, wenn:

- die Status- und Retry-Semantik durch Tests fuer alle relevanten Sequenzen belegt ist
- kein terminaler Erfolg versehentlich erneut versendet wird
- echte Fehler nicht durch Fallbacks oder leere Queues verdeckt werden
- Skip-Gruende und malformed rows in SQL, `/status`, Healthcheck und Applet konsistent erscheinen
- die gezielten Tests und die isolierte Integrationsprobe erfolgreich sind
- eine Live-Probe ohne Datenmutation erfolgreich durchgefuehrt wurde
- die Ergebnisse, Version und Commit-ID hier eingetragen sind
- der Plan erst danach nach `Pläne und Regeln/` archiviert wird

## Nachweisprotokoll

### Bereits vorhanden

- `tests/test_version_notifications.py`: letzter kompletter Lauf im aktuellen Arbeitsstand `214 passed`
- Live-Chat-Status: `status=warning queued=0 failed=0 total=1467 skipped=101 problem_statuses=skipped:101 skip_reasons=no_private_route:101`
- TBL-Produktionsbestand: `1.366 accepted`, `101 skipped`
- Applet- und Statuslogik fuer Bridge-Delegation, malformed rows und `created_at`-Latest-Auswahl umgesetzt
- Reproduktion des Dispatcherfehlers vor dem Fix: ein `skipped/no_private_route`-Resultat endete als `queued`
- History-Dispatcher nach dem Fix: `31 passed`, davon zwei Regressionstests fuer terminale Skips und `delivered+skipped`
- Lokale Dispatcher-Paketversion: `0.2.5`, nach dem Delete-Revision-Fix in `.venv-py313` installiert
- History-Dispatcher-Fixes committed als `943d349` (`Treat skipped recipients as terminal`), `bf78436` (`Report persisted history append status`), `162f978` (`Keep claim response timestamps current`), `90e4206` (`Preserve duplicate uncertainty across retries`) und `84fa05f` (`Bump history dispatcher to 0.2.4`)
- TeeBotus-Plan-/Nachweisstaende committed als `18b36730`, `0cf5db99`, `0d1d2004`, `f3089e08`, `418ba283`, `e9bae24d` und `40c98557`

### In dieser Runde erledigt

- Dispatch-Statussequenztests: erfolgreich; `failed` bleibt retrybar, `skipped` terminal.
- Isolierte Vorher-/Nachher-Probe: vorher `queued`, nachher `skipped`.
- History-Dispatcher-Gesamtsuite: `33 passed`.
- History-Dispatcher-Gesamtsuite nach dem Duplicate-Flag-Fix: `35 passed`.
- History-Dispatcher-Gesamtsuite nach dem Delete-Revision-Fix: `36 passed`.
- TeeBotus Bridge-/Codex-History-Tests: `108 passed`.
- API-Statusprobe: vorher `api_status=queued, stored_status=delivered`; nach dem Fix bestaetigt `api_status=delivered, stored_status=delivered`.
- Claim-Zeitprobe: vorher `claimed_updated_at` alt und `stored_updated_at` neu; nach dem Fix bestaetigt `claim_timestamps_match=True`.
- Duplicate-Flag-Probe: vorher global `possible_duplicate=False` nach erfolgreichem Retry; nach dem Fix muss es global `True` bleiben.
- Delete-Race-Probe: eine parallele Aenderung zwischen Preview und Execute muss jetzt `revision_changed` liefern und den Ziel-Eintrag erhalten.
- Delete-Revision-Fix committed als `94556cb` (`Make delete revision checks atomic`).

### Noch offen

- Semantik spaeter Fehler nach `delivered`/`acknowledged` in einem expliziten neuen Retry-Versuch weiter pruefen.
- Ergebnis des abschliessenden Live- und Applet-Abgleichs eintragen.
- Abschlussversion und finalen Commit erst bei Abschluss des gesamten Bauplans eintragen.

## Betriebsgrenzen

- Kein Push ohne ausdrueckliche Aufforderung.
- Bot-/Service-Restart nur nach der vereinbarten Commit-Grenze oder ausdruecklich angefordert.
- Secrets, Tokens und private Nachrichten gehoeren nicht in diesen Plan.
- Der Plan bleibt unter `Baupläne/`, bis Umsetzung, Tests und Nachweise vollstaendig sind.
