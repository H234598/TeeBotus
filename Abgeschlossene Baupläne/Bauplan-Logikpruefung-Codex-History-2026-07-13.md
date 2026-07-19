# Aktueller Bauplan: Logikpruefung Codex-History und Health-Status

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Bezug:** `Abgeschlossene Baupläne/Healthcheck-Applet-Plan.md`
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
- Der aktuelle TeeBotus-Stand ist nach der Dispatcher-Detailstatus-Korrektur Version `1.9.411`; der laufende Bot-Dienst bleibt bis zur naechsten 20-Commit-Grenze bei `1.9.404`.

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

**Siebzehnter Befund 2026-07-13:** Unbekannte Empfaengerstatuswerte wurden in
der Bridge nur auf Nicht-Leerheit geprueft. Dadurch konnte ein Status wie
`sent` erneut versendet werden, obwohl der Dispatcher ihn fachlich als Fehler
behandelt. Zulassig sind jetzt nur `accepted`, `delivered`, `acknowledged`,
`failed` und `skipped`; alles andere wird kontrolliert abgewiesen.

**Achtzehnter Befund 2026-07-13:** Wenn der externe Collector einen Turn vor
dem TeeBotus-Mirror anlegt, fehlen dort Version, Summary-Prefix und vollstaendige
Markdown-Metadaten. Die Bridge reicherte den externen Payload bisher nicht aus
dem lokalen Eintrag mit demselben Dedupe-Key an und konnte dadurch
`Release <Repo> untagged` versenden. Lokale Payloaddaten werden jetzt bei
gleicher ID oder gleichem Dedupe-Key vor Dry-Run und Versand uebernommen.

**Neunzehnter Befund 2026-07-13:** Ein bereits terminal deduplizierter
Dispatcher-Eintrag (`delivered`, `failed`, `skipped` oder `compacted`) erzeugte
keinen neuen Claim. Der lokale Mirror blieb deshalb trotzdem `queued`. Der
Mirror synchronisiert solche Append-Antworten jetzt direkt, ohne einen
kuenstlichen Versandversuch zu zaehlen.

**Zwanzigster Befund 2026-07-13:** Nach einem frueheren `failed`-Versuch blieb
dessen `last_reason` lokal stehen, obwohl ein spaeterer Dispatcher-Endstatus
bereits `delivered` meldete. Die Reconciliation verwendet jetzt den aktuellen
Versuch fuer den Fehlergrund; erfolgreiche bzw. kompaktierte Endzustaende
entfernen einen veralteten Grund.

**Einundzwanzigster Befund 2026-07-13:** Die Bridge gab ein lokales
`accepted`-Ergebnis aus, obwohl der History-Dispatcher dieselbe erfolgreiche
Zustellung als `delivered` normalisiert. Bridge-Reports und lokale
`last_dispatch_results` normalisieren diese Status jetzt ebenfalls.

**Zweiundzwanzigster Befund 2026-07-13:** Wenn ein alter Empfaenger noch
`failed` war und nur ein anderer Empfaenger erfolgreich erneut bedient wurde,
meldete die Bridge bisher `ok=true` und unterschlug den offenen Fehler. Der
Report fuehrt jetzt alte und aktuelle Empfaengerergebnisse pro Empfaenger
zusammen; ein nicht behobener Fehler bleibt als `failed` sichtbar.

**Dreiundzwanzigster Befund 2026-07-13:** Doppelte oder widerspruechliche
`recipient_id`/`account_id`-Angaben konnten durch die Bridge bis zum
Dispatcher gelangen; dort haette die letzte Zeile die erste ueberschrieben.
Solche Antworten werden jetzt fail-closed abgewiesen.

**Vierundzwanzigster Befund 2026-07-13:** Die lokale Gesamtstatuslogik
behandelte `accepted + skipped` anders als der Dispatcher und lieferte
`accepted` statt `delivered`. Die Aggregation ist jetzt fuer diese gemischte
Erfolg/Skip-Konstellation angeglichen.

**Fuenfundzwanzigster Befund 2026-07-13:** Ein synthetischer
`no_recipient_accounts`-Skip besitzt absichtlich keine Empfaenger-ID und wurde
bei der Empfaengerzusammenfuehrung aus dem Bridge-Report entfernt. Anonyme
Skip-/Fehlerzeilen bleiben jetzt im Bericht, werden aber nicht als echte
Completion-Ziele gesendet.

**Sechsundzwanzigster Befund 2026-07-13:** Der Shadow-/Bridge-Append gab den
lokalen Status und Versuchszahler nicht an `history.append` weiter. Ein lokal
bereits akzeptierter Eintrag konnte dadurch extern wieder als `queued` angelegt
werden. Status, sicher normalisierter Versuchszahler und letzter Fehler werden
jetzt mitgespiegelt.

**Siebenundzwanzigster Befund 2026-07-13:** Die verschachtelte
Dispatcher-Antwortpruefung akzeptierte `data.ok=0`, `null` oder Textwerte. Wenn
das optionale Feld vorhanden ist, muss es jetzt exakt Boolean `true` sein.

**Achtundzwanzigster Befund 2026-07-13:** Im Bridge-Modus wurden neue
Versandresultate wegen `persist_result=False` nicht in
`codex_history_dispatch_results` abgelegt. Replys und Delivery-Receipts konnten
die Summary lokal deshalb nicht wiederfinden. Neue Bridge-Resultate werden jetzt
idempotent lokal gespiegelt.

**Neunundzwanzigster Befund 2026-07-13:** Externe Dispatcher-IDs koennen von
lokalen Outbox-IDs abweichen. Die lokale Resultatspur verwendet bei einem
passenden Dedupe-Key jetzt die lokale ID, damit Reply-/Receipt-Matching und
lokale Statusupdates denselben Eintrag referenzieren.

**Dreissigster Befund 2026-07-13:** Bei mehrfach vorhandenen lokalen
Dedupe-Keys konnte die erste, veraltete Zeile fuer Payload-Enrichment verwendet
werden. Exakte IDs haben jetzt Vorrang; reine Dedupe-Treffer werden nach
`updated_at`/`created_at` ausgewaehlt.

**Einunddreissigster Befund 2026-07-13:** Wenn das Spiegeln der lokalen
Resultat-Collection fehlschlaegt, liegt die Versandspur weiterhin im
Outbox-Feld `last_dispatch_results`. Reply-/Receipt-Matching nutzt dieses Feld
jetzt als lesenden Fallback.

**Zweiunddreissigster Befund 2026-07-13:** Das lokale
`possible_duplicate`-Signal wurde beim Mirror nicht an `history.append`
weitergegeben. Der Warnmarker wird jetzt auf Top-Level und aus dem Delivery-
Unterobjekt uebernommen.

**Dreiunddreissigster Befund 2026-07-13:** Ein zwischen Snapshot und Claim
angelegter lokaler Outbox-Eintrag konnte bei der ID-Zuordnung verpasst werden.
Bei fehlendem Snapshot-Treffer erfolgt jetzt ein einmaliger frischer, lesender
Abgleich.

**Vierunddreissigster Befund 2026-07-13:** Generische Erfolgsgruende wie
`accepted` oder `already_dispatched` konnten als `last_reason` stehen bleiben
und wie ein Fehlergrund aussehen. Erfolgsendzustaende entfernen diese
generischen Marker.

**Fuenfunddreissigster Befund 2026-07-13:** Doppelte Item-IDs in einer
Dispatcher-Antwort konnten denselben Claim mehrfach verarbeiten. Die
Antwortvalidierung weist doppelte IDs jetzt vor der Verarbeitung ab.

**Sechsunddreissigster Befund 2026-07-13:** Eine Completion-Antwort mit
`data.ok=true`, aber ohne gueltigen Top-Level-Status konnte durch lokale
Resultate ersetzt und als Erfolg behandelt werden. Completion-Statuswerte
werden jetzt strikt gegen das Dispatcher-Schema validiert.

**Siebenunddreissigster Befund 2026-07-13:** Ein Claim mit explizitem Status
`delivered` oder anderem Nicht-`delivering`-Wert waere erneut versendet worden.
Explizite Claim-Statuswerte muessen jetzt `delivering` sein; fehlende Werte
bleiben fuer alte Dispatcher-Versionen kompatibel.

**Achtunddreissigster Befund 2026-07-13:** Lokales Reply-/Receipt-Matching
funktioniert fuer bridged Resultate jetzt auch bei unterschiedlichen lokalen
und externen Item-IDs. Der externe `delivery.record`-Pfad schreibt derzeit aber
nur ein Audit-Ereignis und aktualisiert keine `recipient_results`. Ein Receipt
vor oder ohne erfolgreiches `dispatch.complete` kann deshalb extern weiter als
retrybar gelten. Dafuer ist ein separater Cross-Repo-Protokoll-/Store-Fix
noetig; der Code-Fix ist umgesetzt, der Live-Nachweis bleibt offen.

**Umsetzung zum achtunddreissigsten Befund:** History-Dispatcher `0.2.8`
aktualisiert `recipient_results` bei idempotenten `delivered`-/`read`-Events
monoton. TeeBotus spiegelt Bridge-Receipts und Replies mit der externen
Dispatcher-ID und deterministischer Event-ID. Die lokalen Resultate behalten
gleichzeitig die lokale Outbox-ID fuer Reply-/Receipt-Matching.

**Neununddreissigster Befund 2026-07-13:** `delivery.record` verwendete die
vom Channel gelieferte `occurred_at`-Zeit als persistierte Update-Zeit. Alte oder
zukuenftige Events konnten dadurch Queue-Reihenfolge und Statushistorie
verfaelschen. Persistierte Zustandszeiten verwenden jetzt Serverzeit; die
Ereigniszeit bleibt im Audit erhalten.

**Vierzigster Befund 2026-07-13:** Malformierte `delivery`-Metadaten wurden
beim Attempt-Count toleriert, beim Duplikatflag aber direkt als Mapping benutzt.
Der Append-Pfad normalisiert das Unterobjekt jetzt einmal defensiv.

**Einundvierzigster Befund 2026-07-13:** Eine Receipt fuer eine nicht mehr
existierende Item-ID konnte wegen der Foreign-Key-Relation als interner
SQLite-Fehler aus dem Handler fallen. `delivery.record` liefert jetzt
kontrolliert `unknown_item`.

**Zweiundvierzigster Befund 2026-07-13:** Leere oder nur aus Whitespace
bestehende Dedupe-Keys kollidierten beim Append. Nach der Normalisierung faellt
ein leerer Key jetzt auf die individuelle Item-ID zurueck.

**Dreiundvierzigster Befund 2026-07-13:** Eine explizite Item-ID aus
Whitespace wurde als gueltiger Primärschluessel gespeichert. Item-IDs werden
jetzt vor dem Fallback ebenfalls getrimmt.

**Vierundvierzigster Befund 2026-07-13:** Dedupe-Keys mit mehr als 512 Zeichen
wurden abgeschnitten und konnten bei gleichem Praefix kollidieren. Ueberlange
Keys werden jetzt durch einen stabilen SHA-256-Schluessel ersetzt.

**Fuenfundvierzigster Befund 2026-07-13:** Eine bereits verwendete Item-ID mit
anderem Dedupe-Key loeste einen unbehandelten Primary-Key-Fehler aus. Der
Append-Pfad meldet jetzt explizit `item_id_conflict`.

**Sechsundvierzigster Befund 2026-07-13:** Direkte `dispatch.complete`-Clients
konnten doppelte, widerspruechliche oder unbekannte Empfaengerstatus senden;
SQLite uebernahm sonst still die letzte Zeile. Der Store validiert Identitaeten
und Statuswerte jetzt selbst fail-closed.

**Siebenundvierzigster Befund 2026-07-13:** Eine fehlerhafte Completion liess
den bereits geclaimten Eintrag bis zum Claim-TTL blockiert. Nach validierter
Ownership wird ein malformed Completion-Body jetzt auf `queued` zurueckgesetzt,
ohne einen Versuch zu zaehlen.

**Achtundvierzigster Befund 2026-07-13:** Die Service-Schicht wies
`recipient_results` ausserhalb des Stores ab und umging damit die Claim-
Recovery. Die Array-Validierung liegt jetzt zentral im Store hinter der
Ownership-Pruefung.

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
- Restart nach dem 20. Audit-Commit: `teebotus.service`, `history-dispatcher.service` und `teebotus-codex-history-collector.service` aktiv; History-Dispatcher-Snapshot danach `0.2.5`, Queue `13 queued`, `13 delivered`, `310 compacted`, `last_error` leer.
- Unbekannte-Empfaengerstatus-Pruefung und SemVer-Bump auf `1.9.389` committed als `cdb005f6` (`Reject unknown dispatcher recipient statuses`); gezielte Suite danach `122 passed`.
- Payload-Enrichment aus lokalem Store committed als `70b66952` (`Enrich bridged history payloads from local store`); SemVer-Bump auf `1.9.390` committed als `c0d871f2`; gezielte Suite danach `122 passed`.
- Deduplizierten Terminalstatus synchronisieren und SemVer-Bump auf `1.9.391` committed als `6ba97439` (`Reconcile terminal deduplicated mirror status`); gezielte Suite danach `123 passed`.
- Vor dem 20er-Restart meldete der laufende Snapshot noch `0.1.9`; nach dem Restart ist der aktive History-Dispatcher nachweislich `0.2.5`.
- Fixblock fuer Befunde 20-27 umgesetzt und als `588abd30` committed; SemVer-Bump auf `1.9.392`: stale Fehlergruende, Bridge-Statusnormalisierung, vollstaendige Empfaengeraggregation, Identitaetsvalidierung, gemischte Erfolg/Skip-Status, synthetische Skips, Mirror-Statusweitergabe und strikte `data.ok`-Pruefung.
- Gezielte Regressionstests nach diesem Fixblock: `126 passed in 10.68s` in `tests/test_codex_history.py tests/test_history_dispatcher_bridge.py`.
- Aktuelle lesende Dispatcherprobe: Version `0.2.5`, `queued=0`, `delivered=26`, `last_error` leer; Bridge-Dry-Run fuer TBL: `items=0`, `status_counts={}`, keine Mutation.
- Bridge-Result-/Reply-Probe mit externer ID `external-bridge-local-result` und lokaler Outbox-ID erfolgreich; lokale Receipt-Zuordnung funktioniert.
- Gezielte Regressionstests nach dem zweiten Fixblock: `130 passed in 8.93s` in `tests/test_codex_history.py tests/test_history_dispatcher_bridge.py`.
- History-Dispatcher-Receipt-Reconciliation und Input-Haertung: externe Suite `47 passed`; Commits `0a22881`, `4ff12fc`, `c255124` und `22b0fee`, installierte Venv-Version `0.2.8`.
- Lokale Receipt-Mirror-Probe bestaetigt `delivery.record` mit externer Item-ID und Eventtyp `delivered`; lokale Bridge-Suite danach `130 passed in 12.14s`.
- Spates Receipt nach bekanntem `failed`/`queued`-Empfaenger setzt den externen Gesamtstatus jetzt auf `delivered`, wenn alle bekannten Empfaenger erfolgreich oder uebersprungen sind.
- Dedupe-/ID-/Completion-Haertung fuer Befunde 39-48: `47 passed in 1.32s`; malformed Append-, Receipt- und Completion-Inputs bleiben kontrolliert und Claims werden nicht unnoetig blockiert.
- Retry-Regressionsprobe: terminaler `delivered`-Eintrag bleibt bei `dispatch.retry` unveraendert `delivered`; externe Suite danach `48 passed in 2.07s`, Test-Commit `9af5985`.
- Boundary-Restart am `2026-07-13 05:25:22-24 CEST`: `teebotus.service`, `history-dispatcher.service` und `teebotus-codex-history-collector.service` sind aktiv; TeeBotus `1.9.394`, History-Dispatcher-Snapshot `0.2.7`, `queued=0`, `delivered=26`, `last_error` leer.
- Zweiter Boundary-Restart am `2026-07-13 05:37:28-29 CEST`: alle drei Services aktiv; Dispatcher live `0.2.8`, `queued=0`, `delivered=26`, `last_error` leer. Der Bridge-Dry-Run bleibt `ok=true`, `items=0`, ohne Mutation.
- Live-Bridge-Dry-Run fuer `TeeBotus_Logger`: `ok=true`, `items=0`, `status_counts={}`, keine Mutation. Nach dem Restart keine Runtime-Fehler; die einzige gefilterte Meldung ist die erwartete fehlende GitHub-Tag-Notification `v1.9.394`.
- Befund 49: Der Healthcheck fuehrte fuer jede Instanz erneut `import faster_whisper` in einem Unterprozess aus. Drei lokale Transkriptionsproben dauerten dadurch live etwa `5.6 s + 6.7 s + 6.8 s`; der vollstaendige Runtime-Status ueberschritt den Applet-Timeout von 30 Sekunden und wurde faelschlich als `broken`/`health defekt` angezeigt.
- Umsetzung Befund 49: `TeeBotus.core.youtube._has_python_module()` ist jetzt mit einem prozessweiten `lru_cache(maxsize=32)` versehen. Die Probe bleibt ein echter Importtest, wird innerhalb eines Statuslaufs aber nur einmal pro Modul ausgefuehrt. SemVer-Bump auf `1.9.395`, committed als `32d7d379` (`Cache local module health probes`).
- Regressionstest fuer die Cache-Idempotenz: derselbe Modulname erzeugt nur einen Unterprozessaufruf; lokale Transkriptionssuite bleibt gruen.
- Live-Applet-Abgleich nach dem Fix: Statushelper beendet sich mit `runtime_returncode=0` in `15.47 s`, `command_ok=true`, `output_truncated=false`; `health.status=warning` mit `total_problem_count=3` statt eines kuenstlichen Timeout-`broken`. Die verbleibenden drei Handlungszaehler sind konkret: fehlender `OPENAI_API_KEY` fuer `hard_reasoning`, eine nicht verknuepfte Signal-Identitaet der Depressionsbot-Instanz und der lokale TBL-History-Rueckstand; Qdrant und alle zwei Collections sind `ready`.
- Applet-/Installationsvergleich vor Befund 53: `files/teebotus@H234598/applet.js` und die installierte `/home/teladi/.local/share/cinnamon/applets/teebotus@H234598/applet.js` waren byte-identisch; die damalige gezielte Suite lief mit `314 passed in 86.61s`.
- Befund 50: Bei `TEEBOTUS_HISTORY_DISPATCHER_MODE=bridge` und einer explizit leeren `TEEBOTUS_CODEX_HISTORY_DISPATCH_INSTANCES`-Allowlist behandelte der Dispatcher keine Instanz als Ziel, waehrend der Statuspfad jede Instanz als delegierte Quelle markierte. Dadurch konnten nicht zustellbare Queues faelschlich als `status=ok` erscheinen.
- Umsetzung Befund 50: `_codex_history_queue_is_delegated()` erkennt eine explizit leere Allowlist jetzt als "kein Dispatcher konfiguriert" und delegiert in diesem Zustand keine Instanz. Queued-History bleibt dadurch als Warnung sichtbar. SemVer-Bump auf `1.9.396`, committed als `c7964a4c` (`Do not hide history with empty bridge allowlist`).
- Regressionstest Befund 50: Die vollstaendige `tests/test_entrypoint_compatibility.py` laeuft mit `134 passed`; der neue Test verifiziert `status=warning`, `queued=1` und das Fehlen von `dispatch_role=source` bei leerer Allowlist.
- Befund 51: Der Dispatcher kennt die Statuswerte `discarded` und `delivering`, der TeeBotus-Statuspfad fuehrte beide aber nicht in seiner Token-Allowlist. `/status` und das Applet zeigten solche Eintraege dadurch als `unknown` und verloren die fachliche Ursache.
- Umsetzung Befund 51: `CODEX_HISTORY_STATUS_TOKENS` kennt `discarded` und `delivering` jetzt explizit. Beide bleiben handlungsrelevant (`warning`), werden aber mit ihrem echten Namen und nicht als `unknown` ausgegeben. SemVer-Bump auf `1.9.397`, committed als `4f5100ec` (`Preserve dispatcher status tokens in runtime status`).
- Regressionstest Befund 51: `tests/test_version_notifications.py` laeuft vollstaendig mit `215 passed`; der neue Test prueft beide Statuswerte in Instanz- und Repository-Zeile.
- Befund 52: Der History-Dispatcher hatte `status_heartbeat_seconds` zwar in seiner Konfiguration, verwendete den Wert aber nirgends. Der Applet-Snapshot konnte dadurch trotz laufendem Dienst stundenlang veraltet bleiben und einen falschen Dispatcher-Zustand anzeigen.
- Umsetzung Befund 52: `DispatcherService` schreibt den Snapshot jetzt in einem stoppbaren Daemon-Heartbeat, der nur im echten `serve()`-Lifecycle gestartet wird und bei Shutdown sauber beendet wird. Dispatcher-SemVer `0.2.9`, committed im separaten Repo als `a90cb48` (`Refresh dispatcher status snapshot heartbeat`).
- Regressionstest Befund 52: Die vollstaendige History-Dispatcher-Suite laeuft mit `49 passed`; der neue Test bestaetigt eine Snapshot-Aktualisierung ohne API-Aufruf. Der laufende Dienst ist weiterhin `0.2.8`, weil kein ausserplanmaessiger Restart ausgefuehrt wird.
- Befund 53: Das TeeBotus-Applet pruefte beim History-Dispatcher nur `payload.ok`; ein Snapshot mit `ok=true` und vorhandenem `last_error` wurde deshalb als `Status: bereit` angezeigt und der Fehler nicht ausgegeben.
- Umsetzung Befund 53: Das Applet behandelt `last_error` jetzt als Warnung und zeigt ihn als `Letzter Fehler` an. SemVer-Bump auf `1.9.398`, committed als `0eda1cd9` (`Surface dispatcher snapshot errors in applet`). Die Quellkopie ist korrigiert; die installierte Kopie ist noch nicht synchronisiert und der laufende Cinnamon-Prozess wurde nicht reloadet.
- Regressionstest Befund 53: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `179 passed`; der neue JavaScript-Test prueft `ok=true + last_error` gegen `Status: Warnung`.
- Befund 54: Ein fehlgeschlagener oder ungueltiger Snapshot-Lesevorgang setzte zwar `historyDispatcherError`, der Statuskopf ignorierte diesen Fehler aber und konnte einen alten Snapshot als `bereit` anzeigen.
- Umsetzung Befund 54: `historyDispatcherError` wird jetzt selbst als Snapshotfehler klassifiziert. Dadurch zeigt das Applet `Status: Warnung` und den Lesefehler auch dann, wenn noch ein alter Payload im Speicher liegt. SemVer-Bump auf `1.9.399`, committed als `eee73e94` (`Treat dispatcher snapshot read errors as warnings`).
- Regressionstest Befund 54: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `180 passed`; der neue Test prueft einen alten gueltigen Payload zusammen mit einem ungueltigen Snapshot-Lesefehler. Die installierte Applet-Kopie ist weiterhin nicht synchronisiert.
- Befund 55: Der Snapshot-Loader validierte nur `schema_version`. Ein Payload mit `ok: "false"` oder ohne Boolean-`ok` konnte deshalb als gueltig und im Statuskopf als bereit erscheinen.
- Umsetzung Befund 55: Der Loader akzeptiert jetzt nur `schema_version=1` mit echtem Boolean-`ok`; die Anzeige klassifiziert malformed `ok` zusaetzlich fail-closed als Warnung. SemVer-Bump auf `1.9.400`, committed als `14e9d332` (`Reject malformed dispatcher snapshot status`).
- Regressionstest Befund 55: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `181 passed`; der neue Test prueft `ok="false"`. Die installierte Applet-Kopie ist weiterhin nicht synchronisiert.
- Befund 56: Ein gueltiger Snapshot mit `generated_at` in der Zukunft wurde wegen der einseitigen Alterspruefung als `Status: bereit` angezeigt. Das konnte eine falsche Systemuhr oder einen manipulierten Snapshot als gesund tarnen.
- Umsetzung Befund 56: Die Applet-Zeitpruefung verwendet jetzt eine fuenfminuetige Zukunftstoleranz. Ungueltige oder deutlich zukuenftige Zeitstempel werden als `Status: Warnung` klassifiziert; nur ein plausibel alter Zeitstempel wird als `veraltet` markiert. SemVer-Bump auf `1.9.401`.
- Regressionstest Befund 56: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `182 passed`; der neue Test prueft einen Snapshot zwei Stunden in der Zukunft. Eine direkte Vorher-Probe reproduzierte zuvor `Status: bereit`.
- Befund 57: Der Snapshot-Loader pruefte nur `schema_version` und `ok`. Falsch typisierte `collector`-/`dispatch`-Felder konnten deshalb als `aus` erscheinen, waehrend der Status `bereit` blieb.
- Umsetzung Befund 57: Eine gemeinsame `_historyDispatcherSnapshotIsValid`-Pruefung verlangt jetzt gueltiges `generated_at`, Objektstrukturen fuer `collector` und `dispatch` sowie eine Array-Struktur fuer `queue_preview`. Der Loader und die Anzeige verwenden dieselbe Pruefung und bleiben bei Abweichungen warnend. SemVer-Bump auf `1.9.402`.
- Regressionstest Befund 57: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `183 passed`; der neue Test prueft `collector: "broken"` und `dispatch: []`. Eine direkte Vorher-Probe reproduzierte zuvor `Status: bereit` und `Collector: aus`.
- Befund 58: Auch korrekt geformte `collector`-/`dispatch`-Objekte mit Stringwerten wie `enabled: "false"` oder `paused: "false"` wurden durch Truthiness als aktiv beziehungsweise pausiert angezeigt.
- Umsetzung Befund 58: Die Snapshot-Pruefung verlangt jetzt echte nichtnegative Integer fuer `queued`/`total`/`collector.sources` und echte Booleans fuer die sichtbaren Collector-/Dispatch-Schalter. SemVer-Bump auf `1.9.403`.
- Regressionstest Befund 58: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `184 passed`; der neue Test prueft beide String-Boolean-Formen.
- Befund 59: Ein zweiter Dispatcher-Refresh waehrend eines laufenden asynchronen Snapshot-Reads wurde verworfen. Bei deaktiviertem Auto-Refresh konnte dadurch ein alter Runtime-Pfad beziehungsweise Snapshot dauerhaft stehenbleiben.
- Umsetzung Befund 59: Der Applet-Statuspfad merkt einen konkurrierenden Refresh jetzt als Pending und fuehrt ihn nach Abschluss des laufenden Reads genau einmal aus. Beim Entfernen des Applets wird der Pending-Zustand verworfen. SemVer-Bump auf `1.9.404`.
- Regressionstest Befund 59: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `185 passed`; der neue Test bestaetigt, dass ein Refresh waehrend eines laufenden Reads gepuffert wird.
- Live-Nachweis nach Befund 59: Nach 23 Commits seit der letzten Restart-Grenze wurden `teebotus.service`, `history-dispatcher.service` und `teebotus-codex-history-collector.service` am `2026-07-13 06:41:31-32 CEST` kontrolliert neu gestartet. Alle drei sind `active`; der laufende TeeBotus meldet `v1.9.404`, der Dispatcher-Snapshot `version=0.2.9`, `ok=true`, `queued=0`, `total=336` und `last_error` leer. Die installierte Applet-Kopie ist byte-identisch zur Quelle; `ReloadExtension(teebotus@H234598, APPLET)` war erfolgreich.
- Befund 60: Dispatcher-Fehler wurden nur im Untermenue bewertet. Bei ansonsten gesundem Bot zeigte der obere Applet-Header deshalb weiterhin `Health ok` und verschwieg den Fehler.
- Umsetzung Befund 60: Dispatcher-Warnungen und veraltete Snapshots fliessen jetzt in die obere Problemzahl, den effektiven Health-Status und die Detailzeile ein. SemVer-Bump auf `1.9.405`.
- Regressionstest Befund 60: Die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `186 passed`; der neue Test reproduziert einen gesunden Bot mit `last_error` im Dispatcher und erwartet `Warnungen 1`, `Health Warnung` sowie `Dispatcher Warnung`.
- Live-Nachweis Befund 60: Die Applet-Quelle wurde nach Commit `7807d650` installiert und per `ReloadExtension(teebotus@H234598, APPLET)` geladen; `cmp` bestaetigt Byte-Identitaet. Der Bot-Service bleibt bewusst bei `1.9.404`, bis die naechste 20-Commit-Restart-Grenze erreicht ist.
- Befund 61: Bei `classification_version=2` vertraute der Applet-Healthpfad `health.total_problem_count` blind. Ein widerspruechlicher Payload mit `total_problem_count=0` und `actionable_problem_statuses=missing_key:1` wurde dadurch als akzeptabel behandelt beziehungsweise zeigte den Fehler nur ohne Warnungszaehler.
- Umsetzung Befund 61: Die V2-Aggregation nimmt jetzt das Maximum aus dem Gesamtzaehler und den expliziten handlungsrelevanten V2-Zaehlern/Statuslisten. Informationsstatus bleiben bewusst ausgeschlossen. SemVer-Bump auf `1.9.406`.
- Regressionstest Befund 61: Der neue Widerspruchstest prueft Zaehler, sichtbare Warnung und fail-closed Payload-Annahme; gezielt `11 passed`, vollstaendige `tests/test_cinnamon_applet.py` `187 passed in 33.78s`.
- Live-Nachweis Befund 61: `scripts/install_cinnamon_applet.py` wurde erfolgreich ausgefuehrt, Quelle und installierte `applet.js` sind byte-identisch, und `ReloadExtension(teebotus@H234598, APPLET)` wurde erfolgreich angefordert. Kein Bot-/Service-Restart ausserhalb der 20-Commit-Grenze.
- Befund 62: Der Applet-Status verwendete `payload.version` aus dem lokalen Quellcode als scheinbare Laufzeitversion. Nach einem lokalen Version-Bump konnte der Kopf deshalb `Health ok` und eine aktuelle Version zeigen, obwohl der laufende systemd-Bot noch eine alte Version ausfuehrte.
- Umsetzung Befund 62: Der Bot schreibt bei einem echten systemd-Start einen kleinen atomaren Marker unter `data/runtime/teebotus-runtime-version.json` mit SemVer, PID und `INVOCATION_ID`. Der Applet-Helper liest ihn nur als gueltig, wenn PID und systemd-Invocation exakt zur aktiven Unit passen. Die Detailzeile trennt jetzt `Version` (Quellstand) von `Runtime-Version` (laufender Prozess); bei fehlendem oder stale Marker wird nicht geraten.
- Regressionstest Befund 62: Marker-Match, PID-Mismatch und Invocation-Mismatch sind direkt getestet; der normale `main()`-Lebenszyklus erzeugt und entfernt den eigenen Marker ebenfalls nachweisbar. Die vollstaendige Applet-Suite laeuft mit `190 passed`; die relevanten Entry-Point-Tests mit `92 passed, 43 deselected`.
- Live-Nachweis Befund 62: Der laufende Dienst bleibt wegen der 20-Commit-Restart-Grenze noch bei `1.9.404`; der neue Marker wird beim naechsten zulaessigen Neustart erzeugt. Applet-Quelle und Installation werden nach dem Commit erneut byte-identisch installiert und reloadet.
- Befund 63: Der obere Applet-Header und die Detailansicht beschrifteten auch einen `Health: warning`-Zustand als `Probleme N`, waehrend die Statuszusammenfassung bereits `Warnungen N` verwendete. Das war fachlich widerspruechlich und erschwerte die Unterscheidung zwischen Warnung und Defekt.
- Umsetzung Befund 63: Die gemeinsame Applet-Label-Logik verwendet fuer `warning` jetzt `Warnungen`; `broken` und unbekannte Fehlerzustaende bleiben `Probleme`. Die Beschriftung gilt fuer Header und Health-Detailzeile.
- Regressionstest Befund 63: Die Warn-Header-, Warn-Detail- und Dispatcher-Warnproben sind gezielt mit `33 passed` gelaufen; die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `191 passed`.
- Live-Nachweis Befund 63: Die installierte Applet-Kopie wird nach diesem Fix erneut aktualisiert und per Cinnamon-`ReloadXlet` geladen. Kein Bot-/Service-Restart ausserhalb der 20-Commit-Grenze.
- Befund 64: Die Status-Detailansicht addierte Dispatcher-Fehler nicht zum Health-Gesamtwert und leitete den effektiven Status nicht aus dem Dispatcher ab. Ein gesunder Bot-Payload konnte dadurch `Health: ok | Dispatcher Warnung` anzeigen.
- Umsetzung Befund 64: `_statusDetailLines()` verwendet jetzt dieselbe Dispatcher-Problemzahl und den effektiven `warning`-Status wie der obere Header. Die Detailzeile zeigt bei einem gueltigen Snapshot mit `last_error` nun `Health: Warnung | Warnungen 1 | Dispatcher Warnung`.
- Regressionstest Befund 64: Der neue Dispatcher-Detailtest reproduziert den Fehlerfall; die vollstaendige `tests/test_cinnamon_applet.py` laeuft mit `192 passed`.
- Live-Nachweis Befund 64: Die installierte Applet-Kopie wird nach dem Fix erneut byte-identisch aktualisiert und per Cinnamon-`ReloadXlet` geladen. Kein Bot-/Service-Restart ausserhalb der 20-Commit-Grenze.

**Befund 65 2026-07-13:** Im Bridge-Modus wurden alte lokale TBL-History-Zeilen
nicht in die zentrale Dispatcher-Queue nachgefuehrt. Der Bridge-Worker
claimte nur zentrale Eintraege; der lokale Mirror lief bisher nur beim
Erzeugen neuer Summaries. Dadurch blieben lokale queued-Zeilen dauerhaft als
Warnung sichtbar, obwohl der zentrale Dry-Run `statuses: none` meldete.

**Umsetzung Befund 65:** Der Bridge-Dispatchpfad spiegelt jetzt vor
`dispatch.claim` alle lokalen dispatchbaren Zeilen idempotent per
`history.append`. Dedupe-Antworten mit terminalem Status synchronisieren
die lokale Outbox ohne kuenstlichen Versandversuch. Der Dry-Run fragt bei
lokalem Rueckstand den zentralen Bestand nicht mutierend ab und meldet
`would_mirror` beziehungsweise `would_sync`; Append-Fehler bleiben lokal
queued und werden als Fehler zurueckgegeben.

**Regressionstest Befund 65:** Die vollstaendige
`tests/test_codex_history.py`-Suite laeuft mit `128 passed`. Die Bridge-
Teilmenge laeuft mit `24 passed`. SemVer-Bump auf `1.9.411`.

**Live-Dry-Run Befund 65:** Die reale TBL-Probe mit `--dry-run --limit 1000`
meldete `would_mirror=40` und `would_sync=4` bei `44` lokalen queued-Zeilen.
Es wurden weder `history.append` noch `dispatch.claim` oder lokale Schreibungen
ausgefuehrt. Der Bestand bleibt bis zur kontrollierten Freigabe unangetastet.

**Befund 66 2026-07-13:** `_overall_dispatch_reason()` bevorzugte bei
`accepted + skipped` den Skip-Grund gegenueber dem erfolgreichen Ergebnis.
Der Gesamtstatus war zwar `delivered`, aber `last_reason` konnte dadurch
irrefuehrend `no_private_route` bleiben.

**Umsetzung Befund 66:** Die Reason-Aggregation richtet sich jetzt zuerst
nach dem Gesamtstatus. Erfolgreiche Gesamtzustaende uebernehmen nur
Erfolgsgruende und loeschen keinen Fehlergrund aus einem Skip; reine Skips
behalten ihren begruendeten Skip-Grund.

**Regressionstest Befund 66:** `accepted + skipped` ergibt `delivered` mit
leerem Gesamt-Reason; ein alter `last_reason` wird entfernt. Der gezielte
Testlauf war erfolgreich. SemVer-Bump auf `1.9.411`.



### Noch offen

- Retry-Semantik geprueft: `dispatch.retry` downgradet terminale `delivered`-/`acknowledged`-Zustaende nicht; automatische Retries bleiben auf `failed`/`skipped`/`discarded` begrenzt.
- Receipt-/Reply-Reconciliation nach dem Live-Restart durch Dispatcher-Version `0.2.9` und Bridge-Dry-Run belegt; eine echte neue Channel-Zustellung bleibt als optionaler End-to-End-Test offen.
- Live- und Applet-Abgleich ist abgeschlossen; die verbleibenden Warnungen sind jetzt getrennt von Timeout-/Parserfehlern sichtbar und muessen fachlich beziehungsweise durch Benutzeraktion bearbeitet werden.
- Dispatcher-Dry-Run fuer `TeeBotus_Logger` lieferte vor der Reconciliation im Bridge-Modus `statuses: none`, waehrend die lokale Outbox `44 queued` Legacy-Zeilen enthielt. Die schreibfreie Live-Probe meldete danach `would_mirror=40` und `would_sync=4`; keine automatische Loeschung oder Quarantaene erfolgt.
- Der lokale TeeBotus-Code und das laufende Applet sind aktuell `1.9.411`; der laufende Bot-Dienst ist noch `1.9.404`, der aktive History-Dispatcher `0.2.9`. Die untracked Nutzerdaten (`.obsidian/`, `.stfolder/`, `Fusion_Packliste.txt`, `Unbenannt.base`, `Unbenannt.canvas`) bleiben bewusst unberuehrt.
- Abschlussversion und finalen Commit erst bei Abschluss des gesamten Bauplans eintragen.

## Betriebsgrenzen

- Kein Push ohne ausdrueckliche Aufforderung.
- Bot-/Service-Restart nur nach der vereinbarten Commit-Grenze oder ausdruecklich angefordert.
- Secrets, Tokens und private Nachrichten gehoeren nicht in diesen Plan.
- Der Plan bleibt unter `Abgeschlossene Baupläne/`, bis Umsetzung, Tests und Nachweise vollstaendig sind.
