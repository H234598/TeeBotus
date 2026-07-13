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
- Der aktuelle TeeBotus-Stand ist Version `1.9.388`, Commit `ed4b2d0f`.

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

**Sechster Befund 2026-07-13:** Der History-Dispatcher kann einen technischen
Transporterfolg mit einem fachlichen Fehler in `data.ok=false` beantworten.
Der TeeBotus-Bridge-Worker pruefte bisher nur das aeussere `ok` und behandelte
`claim_not_owned` dadurch als erfolgreichen Abschluss. Die Auswertung prueft
jetzt beide Ebenen und bricht fail-closed ab.

**Siebter Befund 2026-07-13:** Erfolgreiche Dispatcher-Antworten wurden ohne
Schema-Pruefung direkt mit `.get()` verarbeitet. `data=null` konnte deshalb
einen ungefangenen `AttributeError` ausloesen; fehlende oder falsch typisierte
`items` konnten still als leere Queue erscheinen. Die Bridge validiert `data`
und `items` jetzt vor der Verarbeitung und wandelt Abweichungen in einen
kontrollierten Dispatcher-Fehler um.

**Achter Befund 2026-07-13:** Die Bridge uebersprang nicht-objektartige Claim-
Items, akzeptierte `recipient_results=null` bzw. unvollstaendige Empfaengerzeilen
und behandelte `dispatch.complete` mit `data=null` als Erfolg. Dadurch konnte ein
Claim ohne Abschluss im `delivering`-Zustand haengen oder eine leere/ungueltige
Zustellung als erfolgreich erscheinen. Ausserdem fragte der Dry-Run die Payload
nicht an und verlor dadurch Summary-Metadaten. Items, Payload, Empfaenger und
Completion-Antwort werden jetzt fail-closed validiert; der Dry-Run fordert die
Payload explizit an.

**Neunter Befund 2026-07-13:** Die Socket-Pfadvalidierung lief vor dem
Bridge-Fehlerhandler. Ein relativer oder anderweitig unsicherer
`HISTORY_DISPATCHER_SOCKET` konnte deshalb den Bot aus dem Dispatch-Aufruf
werfen; im Shadow-Modus konnte derselbe Konfigurationsfehler sogar das
eigentliche Legacy-Summary-Schreiben abbrechen. Beide Pfade melden den Fehler
jetzt kontrolliert bzw. lassen den Legacy-Pfad unveraendert fortsetzen.

**Zehnter Befund 2026-07-13:** Der Shadow-Append pruefte nur das aeussere
Response-`ok`. Ein technischer Transporterfolg mit `data.ok=false` konnte
deshalb als erfolgreiches Spiegeln erscheinen. Die Shadow-Antwort wird jetzt
mit derselben verschachtelten Schema-Pruefung wie der Bridge-Completionpfad
ausgewertet; der Legacy-Eintrag bleibt bei einem Shadow-Fehler erhalten.

**Elfter Befund 2026-07-13:** Der Legacy-Pfad behandelte
`codex_history_digest` als nicht dispatchbar, obwohl die Kompaktierungslogik
Digests ausdruecklich als Markdown-Dateien fuer TBL erzeugt. Der Bridge-Pfad
hatte dagegen keine `kind`-Pruefung und haette auch fremde Queue-Typen claimen
koennen. Die gemeinsame Dispatch-Menge enthaelt jetzt Digests; unbekannte
Typen werden in beiden Pfaden nicht als Codex-Summaries verarbeitet.

**Zwoelfter Befund 2026-07-13:** Im Bridge-Modus wurde nach einem externen
`dispatch.complete` der gleichnamige lokale TeeBotus-Outbox-Eintrag nie
aktualisiert. `/status` konnte deshalb beim Dispatcher-Owner dauerhaft
`queued` zeigen, obwohl TBL extern bereits zugestellt oder zur Wiederholung
eingeplant hatte. Der externe Endstatus ist jetzt autoritativ; ein vorhandener
lokaler Eintrag wird best-effort mit Status, Versuch und letzter
Empfaengerliste synchronisiert.

**Dreizehnter Befund 2026-07-13:** Der externe Collector und der TeeBotus-
Watcher scannen dieselben Codex-Sessiondateien. Der Collector nutzt den
deterministischen Session-/Turn-/Final-Hash als `dedupe_key`, der Mirror
ueberschrieb ihn bisher mit der lokalen UUID. Dadurch konnten identische Turns
zweimal in der externen Queue landen. Der Mirror verwendet jetzt den
vorhandenen `codex.dedupe_key` und faellt nur bei manuellen Summaries auf die
Item-ID zurueck.

**Vierzehnter Befund 2026-07-13:** Bei einem bereits extern importierten Turn
liefert `history.append` die externe bestehende ID zurueck. Diese kann von der
lokalen TeeBotus-ID abweichen; eine reine ID-Synchronisierung haette den lokalen
Status weiterhin als `queued` stehen lassen. Die Reconciliation sucht jetzt
zusaetzlich nach dem deterministischen Dedupe-Key. Fehlende `payload.codex`
Metadaten werden dabei als leer behandelt, nicht als Laufzeitfehler.

**Fuenfzehnter Befund 2026-07-13:** Die Legacy-Retryauswahl nahm pro Konto
einfach die letzte Zeile aus der Storage-Reihenfolge. Nach SQL-Rebuilds oder
Importen kann diese Reihenfolge von der fachlichen Ereigniszeit abweichen.
Resultate werden jetzt zuerst nach `updated_at`/`created_at` und nur bei
fehlenden Zeitstempeln nach Positionsreihenfolge bewertet.

**Sechzehnter Befund 2026-07-13:** Der Shadow-Append akzeptierte ein
aeusseres `ok=true` mit `data.ok=true`, aber ohne persistierte Item-ID als
erfolgreiches Spiegeln. Damit waere unklar geblieben, ob ein Eintrag neu
angelegt oder dedupliziert wurde. Erfolgreiche Append-Antworten muessen jetzt
eine ID enthalten; der Legacy-Pfad bleibt bei Verstoessen erhalten.

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
- TeeBotus-Plan-/Nachweisstaende committed als `18b36730`, `0cf5db99`, `0d1d2004`, `f3089e08`, `418ba283`, `e9bae24d`, `40c98557`, `1764b2b9` und `33b383a6`

### In dieser Runde erledigt

- Dispatch-Statussequenztests: erfolgreich; `failed` bleibt retrybar, `skipped` terminal.
- Isolierte Vorher-/Nachher-Probe: vorher `queued`, nachher `skipped`.
- History-Dispatcher-Gesamtsuite: `33 passed`.
- History-Dispatcher-Gesamtsuite nach dem Duplicate-Flag-Fix: `35 passed`.
- History-Dispatcher-Gesamtsuite nach dem Delete-Revision-Fix: `36 passed`.
- TeeBotus Bridge-/Codex-History-Tests vor dem Nested-Response-Fix: `108 passed`; danach `109 passed`, nach der Schema-Pruefung `110 passed`.
- API-Statusprobe: vorher `api_status=queued, stored_status=delivered`; nach dem Fix bestaetigt `api_status=delivered, stored_status=delivered`.
- Claim-Zeitprobe: vorher `claimed_updated_at` alt und `stored_updated_at` neu; nach dem Fix bestaetigt `claim_timestamps_match=True`.
- Duplicate-Flag-Probe: vorher global `possible_duplicate=False` nach erfolgreichem Retry; nach dem Fix muss es global `True` bleiben.
- Delete-Race-Probe: eine parallele Aenderung zwischen Preview und Execute muss jetzt `revision_changed` liefern und den Ziel-Eintrag erhalten.
- Delete-Revision-Fix committed als `94556cb` (`Make delete revision checks atomic`).
- Nested-Completion-Probe: `data.ok=false` mit `claim_not_owned` wird jetzt als fehlgeschlagener Dispatcher-Lauf gemeldet.
- Malformed-Claim-Probe: `data=null` wird jetzt als kontrollierter `history_dispatcher_unavailable`-Fehler gemeldet.
- Bridge-Schema-Proben: nicht-objektartiges Claim-Item, `recipient_results=null` und `dispatch.complete data=null` werden kontrolliert abgewiesen; Dry-Run uebernimmt `summary_prefix` wieder aus der Payload.
- Gezielt verifizierte TeeBotus-Suite nach der Bridge-Haertung: `114 passed`.
- Bridge-Haertung und SemVer-Bump auf `1.9.380` committed als `8376977e` (`Harden history dispatcher bridge validation`).
- Socket-Fehlerbehandlung und SemVer-Bump auf `1.9.381` committed als `e500d915` (`Keep history dispatch socket errors contained`); gezielte Suite danach `116 passed`.
- Shadow-Response-Pruefung und SemVer-Bump auf `1.9.382` committed als `57849ffb` (`Validate shadow dispatcher append responses`); gezielte Suite danach `117 passed`.
- Kind-/Digest-Abgleich und SemVer-Bump auf `1.9.383` committed als `a32dab73` (`Align bridge dispatchable history kinds`); gezielte Suite danach `118 passed`.
- Lokale Status-Reconciliation und SemVer-Bump auf `1.9.384` committed als `54e6d00d` (`Reconcile local history status after bridge completion`); gezielte Suite danach `119 passed`.
- Dedupe-Abgleich und SemVer-Bump auf `1.9.385` committed als `f3efbd38` (`Reuse Codex session dedupe keys in bridge`); gezielte Suite danach `119 passed`.
- Lesende Live-Dispatcherprobe: `336` Zeilen, `0` doppelte Top-Level-Dedupe-Keys; Bestand `13 queued`, `13 delivered`, `310 compacted`.
- Dedupe-Key-Reconciliation mit absichtlich verschiedener externer/lokaler ID verifiziert; lokale Queue wird ueber den Dedupe-Key synchronisiert.
- Dedupe-Reconciliation und SemVer-Bump auf `1.9.386` committed als `fd7400d7` (`Reconcile mirrored history by dedupe key`); gezielte Suite danach `119 passed`.
- Retry-Statusauswahl nach Zeitstempel und SemVer-Bump auf `1.9.387` committed als `0ecbc32f` (`Order dispatch results by update time`); gezielte Suite danach `120 passed`.
- Shadow-Append-ID-Pruefung und SemVer-Bump auf `1.9.388` committed als `ed4b2d0f` (`Require shadow append item identity`); gezielte Suite danach `121 passed`.
- Der laufende History-Dispatcher-Snapshot meldet noch `0.1.9`, die installierte Venv `0.2.5`; der Live-Cutover-/Restart-Nachweis bleibt offen.

### Noch offen

- Semantik spaeter Fehler nach `delivered`/`acknowledged` in einem expliziten neuen Retry-Versuch weiter pruefen.
- Ergebnis des abschliessenden Live- und Applet-Abgleichs eintragen.
- History-Dispatcher nach der Commit-Grenze neu starten und Snapshot-/Bridge-Version erneut pruefen.
- Abschlussversion und finalen Commit erst bei Abschluss des gesamten Bauplans eintragen.

## Betriebsgrenzen

- Kein Push ohne ausdrueckliche Aufforderung.
- Bot-/Service-Restart nur nach der vereinbarten Commit-Grenze oder ausdruecklich angefordert.
- Secrets, Tokens und private Nachrichten gehoeren nicht in diesen Plan.
- Der Plan bleibt unter `Baupläne/`, bis Umsetzung, Tests und Nachweise vollstaendig sind.
