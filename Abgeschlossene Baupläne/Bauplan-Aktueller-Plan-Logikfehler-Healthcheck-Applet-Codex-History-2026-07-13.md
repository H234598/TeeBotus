# Bauplan: Aktueller Plan fuer Logikfehler, Healthcheck, Applet und Codex-History

**Stand:** 2026-07-13

**Status:** Aktiv, neue Momentaufnahme; noch nicht abgeschlossen

**Quellstand:** TeeBotus `1.9.489`, lokaler Stand nach dem Bridge-Route-Preflight-Fix, dem Applet-Queue-Anzeigepatch, dem Watcher-Ressourcenfix, dem Mixed-Route-Dispatchfix, dem Stale-Recipient-Fix und dem Mehrfach-Queue-Report-Fix. Der Funktionscommit ist `d412df5d`.

**Geltungsbereich:** Runtime-Healthcheck, TeeBotus-Cinnamon-Applet, TBL-Adminstatus, Codex-History-Bridge und Collector-Performance

## Auftrag

Die Warnungen und Probleme, die oben im TeeBotus-Applet erscheinen, werden bis
zu ihrer technischen Ursache verfolgt. Echte Betriebsprobleme bleiben sichtbar
und handlungsrelevant. Reine Hinweise, delegierte Quellen, terminale
Nichtzustellungen und bekannte Fallbacks bleiben in der Detaildiagnose erhalten,
werden aber nicht ohne Beleg als Top-Level-Defekt bewertet.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Dieser Bauplan ist die neue kanonische Arbeitskopie des aktuellen Planstands fuer
die Logikfehlerpruefung.
Vorherige Detailplaene bleiben als Historie und Nachweis erhalten:

- `Abgeschlossene Baupläne/Bauplan-Aktueller-Healthcheck-Warnungsabbau-und-Codex-History-Reconciliation-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Planstand-Healthcheck-Warnungen-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Healthcheck-Applet-Aktuelle-Logikpruefung-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Arbeitsstand-Logikpruefung-Codex-History-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Healthcheck-Codex-History-2026-07-13.md`

Der vorherige kanonische Snapshot
`Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Healthcheck-Applet-und-Codex-History-2026-07-13.md`
bleibt unveraendert als Vergleichspunkt erhalten. Neue Nachweise werden ab
jetzt in diesem Bauplan fortgeschrieben.

## Leitplanken

- Sicherheit vor Bequemlichkeit: unbekannte, widerspruechliche oder nicht
  authentisierte Zustaende werden nicht als gesund behandelt.
- Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer Diagnose,
  Reconciliation oder Tests.
- Healthcheck, Status-Applet und Dry-Runs lesen nur. Linking, Requeue,
  Status-Reconciliation, Quarantaene und Konfigurationsaenderungen bleiben
  explizite und nachvollziehbare Aktionen.
- Keine Summarys, Outbox-Zeilen oder Dispatch-Resultate loeschen.
- Secrets, Account-IDs und private Nachrichteninhalte werden nicht in
  Plantexten, Logs oder Applet-Payloads ausgegeben.
- Die uncommitteten Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.
- Kein Push ohne ausdrueckliche Anforderung. Bot-/Service-Restarts erfolgen
  nur an der vereinbarten 20-Commit-Grenze oder nach ausdruecklicher Freigabe.
- Jede abgeschlossene Implementierung erhaelt fokussierte Regressionstests,
  einen lokalen Commit und einen Eintrag mit Nachweis in diesem Bauplan.

## Bereits umgesetzt

### Health-Klassifikation und Applet

- Python-Payload und Cinnamon-Applet verwenden die strukturierte
  `classification_version=2`-Semantik.
- Actionable Probleme, Warnungen und informative Hinweise werden getrennt
  gezaehlt und im Applet kategorisiert angezeigt.
- Deklarative Statuslisten wie `problem_statuses=broken:1` werden fail-closed
  mit strukturierten Zaehlern abgeglichen.
- Gequotete Statuswerte, numerische Werte und Fallback-Metadaten werden
  konsistent normalisiert.
- Ein echter `error=`-Befund bleibt sichtbar; ein belegter gesunder lokaler
  Fallback wird nicht unnoetig als Top-Level-Defekt gewertet.
- Unbekannte oder widerspruechliche Statuswerte werden nicht still als `ok`
  behandelt.
- Die Watch-Payload-Healthpruefung akzeptiert nur echte Boolean-`ok`-Werte;
  malformed Instanz- oder Post-Index-Berichte werden fail-closed abgelehnt.
- Quell- und installierte Applet-Kopie waren zuletzt byte-identisch.
- Die obere Applet-Healthanzeige nennt bei actionable Runtime-Befunden jetzt bis
  zu drei kurze Ursachen. Eine verifizierte lokale Fallback-Route wird dabei
  nicht als actionable Detail ausgegeben.

### Secret-Service- und Adminstatus

- Normale Runtime-Statuspfade verwenden die runtime-konfigurierte
  Secret-Service-Retry-/Timeout-Policy.
- Read-only-Adminlookup verwendet dieselbe Retry-/Timeout-Policy.
- Der Memory-Recovery-Pfad behaelt bewusst seinen separaten read-only Provider,
  damit alte oder defekte Verschluesselungsmetadaten diagnostizierbar bleiben.

### Codex-History-Bridge

- Der zentrale `history-dispatcher.service` laeuft im Bridge-Modus.
- Der zentrale Dispatcher ist read-only nachgewiesen mit `queued=0`,
  `delivered=26`, `compacted=310`, `total=336` und leerem `last_error`.
- TBL besitzt eine routbare Telegram-Adminroute auf Slot 1.
- Delegierte Codex-History-Quellen werden im Bridge-Modus nicht automatisch als
  lokale Fehler hochgestuft.
- Der Bridge-Pfad gleicht nach einem leeren `dispatch.claim` den zentralen
  Bestand nochmals mit `history.query` ab. Eindeutig gematchte terminale
  Dispatcher-Zustaende werden idempotent in die lokale Outbox uebernommen.
  Lokale Zeilen werden nicht geloescht und Recipient-Resultate nicht erfunden.

### Codex-History-Watcher

- Die Snapshot-Dateiauswahl wird zwischen Zustandsvergleich und Import
  wiederverwendet; ein zweiter rekursiver Sessionroot-Scan entfaellt.
- Ein Datei-Ereignis importiert nur betroffene, noch vorhandene JSONL-Pfade
  statt der gesamten `limit`-Menge.
- Bei validierten Ereignissen wird der zusaetzliche Vollsnapshot uebersprungen;
  Erstlauf und Timeout-/Fallbackpfad behalten die Snapshot-Pruefung.
- Bei einem explizit konfigurierten JSONL-Root, dessen Datei beim Start noch
  nicht existiert, wird jetzt der vorhandene Elternordner beobachtet. Eine
  spaeter erzeugte Session kann dadurch als Ereignis erkannt werden.
- Der Watchdog bleibt waehrend Import, Post-Index und Dispatch aktiv. Events
  aus dieser Zeit werden am naechsten Wartepunkt verarbeitet.
- Ein aeusserer Cleanup-Pfad beendet den Watchdog auch bei Scan- oder
  Callback-Exceptions.
- Auch eine Exception aus `Observer.start()` laeuft durch den aeusseren
  Cleanup-Pfad; ein teilweise gestarteter Observer wird best effort gestoppt.
- Fehler aus `Observer.stop()` oder `join()` maskieren keinen Primaerfehler mehr;
  beide Schritte werden versucht und der interne Started-Zustand wird garantiert
  zurueckgesetzt.
- Die Snapshot-Baseline wird nach inkrementellen Events aktualisiert, damit
  ein folgender Timeout bereits verarbeitete Dateien nicht erneut importiert.
- Geloeschte oder umbenannte Eventquellen werden aus der Baseline entfernt,
  ohne geloeschte Dateien erneut importieren zu wollen.
- `missing_final_text` und `invalid_repo_root` werden begrenzt protokolliert;
  die vollstaendigen Zaehler bleiben erhalten.
- Die Follow-Detailausgabe ist auf 12 nicht redundante Detailzeilen begrenzt;
  ausgelassene Details werden explizit gezaehlt.
- Post-Index und Dispatch laufen initial und danach nur bei echten Importen;
  der Idle-Dispatch bleibt als wartende Queue-Pruefung erhalten.
- Post-Index- und Dispatch-Pending-Flags werden nur bei einem strikt echten
  `ok=True` geloescht. Malformed Ergebnisse bleiben retryfaehig und werden als
  fehlerhafte Reports gespeichert.
- Malformed Post-Index-/Dispatch-Reports werden vor Speicherung und
  Follow-Textausgabe in ein strukturiertes Fehlerobjekt normalisiert.
- Benutzerdefinierte Sessionroots werden anhand ihrer tatsaechlichen Root-
  Struktur akzeptiert; ein Pfadsegment `sessions` ist nicht mehr zwingend.
  Agentenroots mit eigener `sessions`-Unterstruktur bleiben gegen fremde
  JSONL-Dateien abgegrenzt.

## Aktueller Live-Befund

### Applet-Health

Eine direkte Probe mit `python -m TeeBotus.cinnamon_applet status` ergab zuletzt:

```text
health.status=warning
health.actionable_problem_count=1
health.informational_problem_count=23
health.runtime_problem_count=1
health.qdrant_problem_count=0
command_ok=true
```

Der einzige actionable Befund war:

```text
account_identity_warning=Depressionsbot code=runtime_channel_without_identity
channel=signal configured_runtime_slots=1 identity_channels=telegram:3
```

Das ist kein Applet- oder Parserfehler. Der Signal-Runtime-Slot ist fuer
`Depressionsbot` konfiguriert, aber noch keiner bestehenden Signal-Identitaet
zugeordnet. Ohne explizites Account-Linking wuerde ein Signal-Eingang einen
separaten Account verwenden. Automatisches Linken bleibt aus
Sicherheitsgruenden verboten.

Die installierte Cinnamon-Datei
`~/.local/share/cinnamon/applets/teebotus@H234598/applet.js` war byte-identisch
mit `files/teebotus@H234598/applet.js` (SHA-256
`9a105af5d2c1c0e6dbfb1c88825991ac0d04cef4f9109d2e4da070b6509733b0`). Ein
veraltetes Applet ist damit als Ursache ausgeschlossen.

Die weiteren 23 Befunde sind klassifizierte Hinweise, unter anderem optionale
Fallbacks, fehlende optionale Keys, unvollstaendige Codex-Usage-Snapshots und
bekannte `no_private_route`-History-Skips.

### TBL-Codex-History

Die lokale TBL-Statusaggregation zeigte zuletzt sinngemaess:

```text
codex_history=TeeBotus_Logger status=warning queued=122 failed=0 total=1591
skipped=101 problem_statuses=queued:122,skipped:101
skip_reasons=no_private_route:101
```

Die zentrale Dispatcher-Wahrheit und die lokale TBL-Spiegelung werden deshalb
getrennt betrachtet:

1. Zentral: keine wartende Queue, kein letzter Dispatcherfehler.
2. Lokal: alte `queued`-Zeilen und terminale `no_private_route`-Resultate.

Offen ist, welche lokalen Zeilen historische Legacy-/Spiegelreste sind und
welche noch nachweislich zugestellt werden muessen. Eine pauschale Requeue-
oder Loeschaktion ist nicht zulaessig.

### Laufzeit-/Quellstand-Abgleich

Eine schreibfreie Systemd-Pruefung am 2026-07-13 bestaetigte:

- `teebotus-codex-history-collector.service` ist aktiv, MainPID `1014623`,
  Startzeit `2026-07-13 06:41:32 CEST`.
- `teebotus.service` ist aktiv, MainPID `1014664`, Startzeit ebenfalls
  `2026-07-13 06:41:32 CEST`.
- Der Quellstand ist inzwischen `1.9.489`; die laufenden Prozesse wurden vor
  den letzten Watcher-/Sessionroot- und Bridge-Route-Fixes gestartet und
  enthalten diese deshalb noch nicht. Das Journal bestaetigt den alten
  Laufzeitstand mit einer Versionsmeldung fuer `1.9.404`.
- `INVOCATION_ID` ist in beiden laufenden Units vorhanden. Das schliesst die
  bisher vermutete fehlende Systemd-Umgebungsvariable als Ursache aus.
- `data/runtime/teebotus-runtime-version.json` fehlt aktuell. Das passt zum
  alten Prozessstand, der den aktuellen Marker-Lifecycle noch nicht enthaelt;
  das Applet darf daraus nur `marker_missing` ableiten, nicht stillschweigend
  eine falsche Version behaupten.

Der Marker-Befund ist damit als aktueller Produktionsfehler nicht reproduziert:
Die aktuelle Quelle schreibt den Marker waehrend des normalen `main()`-
Lebenszyklus und entfernt ihn erst beim Prozessende; die bestehenden Tests
decken Schreiben, Unit-Matching und Cleanup ab. Die Live-Wirkung bleibt bis zum
naechsten erlaubten Restart unbestaetigt.

### Collector-Performance

Der Follow-Collector war zuletzt aktiv, aber ressourcenauffaellig: etwa
1.9 GiB RSS und rund 96 Prozent CPU. Trotz `--poll-interval 300` koennen
Dateisystemereignisse wiederholte Scans ausloesen. Erwartete Skips wegen
`missing_final_text` und `invalid_repo_root` wurden ebenfalls beobachtet.

Der aktuelle read-only Realroot-Vergleich misst:

```text
1000-Datei-Snapshot: 2303.15 ms
Eventpfad-Filter:       0.5543 ms
Baseline-Update:         0.7585 ms
Provider-/Netzwerkcalls: 0
```

Ein lokaler Poll-Benchmark ohne Provideraufrufe ergab ausserdem:

```text
codex_history_watcher_poll_loop
10 Sessiondateien, 10 Iterationen, ok=true
262.27 ms, 38.13 Operationen/s, network_calls=0
```

Die Ursache des hohen Live-Verbrauchs wurde fuer den beobachteten Eventpfad
auf Event-Bursts plus grosse wiederholte Importmengen eingegrenzt. Accountstore-
Lesen und Export bleiben nach Aktivierung des Fixes als Nachmessung offen.

## Offene Arbeitspakete

### Snapshot-Update: Applet-Queuebegriffe

- [x] Im Projekt-History-Menue die lokale Bridge-Outbox als `lokale Outbox
  offen` kennzeichnen, damit sie nicht mit der zentralen Dispatcher-Queue
  verwechselt wird.
- [x] Die zentrale Dispatcher-Queue separat als `Zentraler Dispatcher:
  Queue <queued> / gesamt <total>` anzeigen und ihren Zustand als `bereit`,
  `veraltet` oder `Warnung` ausweisen.
- [x] Den Queuebegriff auch im Repository-Drilldown konsistent verwenden.
- [x] Den vollstaendigen Cinnamon-Applet-Testlauf nach dem Patch stabil gruen
  nachweisen: `232 passed in 38.22s`.
- [x] Applet nach bestandener Vollsuite installieren und Quell-/Installations-
  parity mit `diff -qr` pruefen.
- [x] Version auf `1.9.483` bumpen und den Funktionspatch lokal als
  `7b6da19a` committen.
- [ ] Keinen Bot-/Service-Restart ausserhalb des vereinbarten Restart-Fensters
  ausloesen.

### Snapshot-Update: Follow-Collector-Ressourcen

- [x] Den Live-Befund reproduzieren: Der Follow-Collector lag bei rund
  `2.5 GiB RSS` und `95.8 % CPU`; in zehn Minuten wurden `31` Scans mit je
  `duplicate=909, skipped=91` protokolliert.
- [x] Ursache im Watchdog-Pfad eingrenzen: einzelne JSONL-Schreibvorgaenge
  erzeugten mehrere Events, die ohne Burst-Koaleszenz jeweils erneut grosse
  Sessionmengen und drei AccountStores anstiessen.
- [x] Watchdog-Events bis zu `0.25 s` sammeln, mit einer harten Obergrenze von
  `2.0 s`, damit aktive Sessions weiter erkannt werden, der Import aber nicht
  in einem Event-Sturm busy-looped.
- [x] Follow-Report-Retention von `250` auf `24` Eintraege reduzieren. Das ist
  nur eine RAM-Diagnosegrenze; persistierte Summarys, Zwischenantworten und
  Dispatchdaten werden nicht geloescht oder gekuerzt.
- [x] Regression fuer ein spaet eintreffendes Event waehrend der Debounce-
  Phase ergaenzen; beide Pfade bleiben erhalten.
- [x] Watchdog-Ereignisse nach Typ filtern: `created`, `modified`, `moved`,
  `deleted` und `closed` bleiben relevant; `opened` und `closed_no_write`
  werden ignoriert, damit das reine Lesen durch den Collector keinen eigenen
  Importzyklus ausloest.
- [x] Die installierte Watchdog-Version gegen die Ereignistypen pruefen:
  `FileCreatedEvent=created`, `FileModifiedEvent=modified`,
  `FileMovedEvent=moved`, `FileClosedEvent=closed`,
  `FileClosedNoWriteEvent=closed_no_write`, `FileOpenedEvent=opened`.
- [x] Die verschachtelten Sessionroots im langlebigen Watcher cachen und nur
  bei einem noch existierenden, vom Cache abgewiesenen Eventpfad neu ermitteln.
  Neue Agentenroots bleiben damit erkennbar, waehrend der Normalpfad nicht
  mehr rekursiv ueber alle Agentenverzeichnisse laeuft.
- [x] Read-only-Echtmessung des Eventfilters ausfuehren: ungecacht
  `1963.8 ms`, einmaliger Root-Cache-Aufbau `1917.2 ms`, danach gecacht
  `0.988 ms`; jeweils genau ein Pfad selektiert, `network_calls=0`.
- [ ] Nach dem naechsten erlaubten Restart RSS, CPU, Scanrate und WAL-
  Schreibvolumen erneut live messen. Der laufende Prozess hat den Fix noch
  nicht geladen.

### A. TBL-Reconciliation schreibfrei beweisen

- [ ] Lokale TBL-Outbox, lokale Dispatch-Results und zentrale
  `history_items`/`recipient_results` ueber Item-ID und Dedupe-Key abgleichen.
- [x] Aktuellen Bridge-Dry-Run mit dem Quellstand `1.9.488` schreibfrei
  ausfuehren: `155` lokale Zeilen `would_mirror`, `4` terminale zentrale
  Treffer `would_sync`, `ok=true`; keine Mutation und kein Provideraufruf.
- [ ] Jede lokale `queued`-Zeile als zentral nicht vorhanden, zentral terminal,
  zentral weiterhin queued oder lokale Legacy-Zeile klassifizieren.
- [ ] Jeden `no_private_route`-Skip gegen die zum Skip-Zeitpunkt gueltige
  private Route pruefen.
- [ ] JSON-/Markdown-Report speichern, ohne Daten zu veraendern.
- [ ] Erst nach Review einen idempotenten Reconciliation-Befehl bauen, der nur
  eindeutig zentral bestaetigte terminale Statuswerte lokal nachtraegt.

### B. Bridge-Dispatchfluss pruefen

- [ ] Watcher-Dispatch je Instanz ausgeben und pruefen, ob `TeeBotus_Logger`
  tatsaechlich `dispatch.claim` und `dispatch.complete` erreicht.
- [ ] Belegen, ob `dispatch statuses: none` nur keine neuen Kandidaten bedeutet
  oder ob ein Statusreport verworfen wird.
- [x] Zentrale terminale Ergebnisse idempotent in den lokalen TBL-Spiegel
  schreiben, wenn nach dem Claim kein neuer zentraler Claim vorliegt.
- [ ] Keine pauschale Requeue-Aktion fuer alte `queued`-Zeilen.
- [ ] Applet-Health so erweitern, dass zentrale Queue `0` und lokale
  historische Spiegelreste getrennt benannt werden.

### B1. Mixed-Route-Dispatch

- [x] Logikfehler reproduzieren: Der Bridge-Pfad berechnete zwar
  `routable_account_ids`, versandte danach aber an alle
  `candidate_account_ids`.
- [x] Versand auf die bereits vorgepruefte routbare Teilmenge begrenzen.
- [x] Regression fuer einen routbaren und einen nicht routbaren Admin-
  Empfaenger ergaenzen; nur die routbare ID wird an den Sender und an
  `dispatch.complete` weitergegeben.
- [x] `pytest -q tests/test_codex_history.py tests/test_pyproject_metadata.py`:
  `164 passed in 6.95s`; Compileall und `git diff --check` sauber.
- [x] Patchversion auf `1.9.487` bumpen und als `5c6992dc` committen.
- [ ] Live-Nachweis nach Restart: gemischte Adminroute mit einer tatsaechlich
  nicht routbaren ID pruefen.

### B2. Stale-Recipient-Status

- [x] Logikfehler reproduzieren: Ein alter `failed`-Empfaenger ausserhalb der
  aktuellen routbaren Adminmenge konnte eine neue erfolgreiche Zustellung im
  zentralen Dispatcher weiterhin als `failed`/`queued` blockieren.
- [x] Vorhandene alte Fehlereintraege bei einem neuen Retry als terminalen
  `skipped`-Status mit `reason=recipient_not_routable` melden. Die bestehende
  Empfaenger-ID und die Auditdaten bleiben erhalten; es wird kein neuer
  Empfaenger erfunden.
- [x] Regression bestaetigt, dass `dispatch.complete` den alten Empfaenger
  als Skip und den aktuellen Empfaenger als Erfolg uebergibt.
- [x] `pytest -q tests/test_codex_history.py`:
  `158 passed in 7.17s`; History-/Metadaten-Suite:
  `164 passed in 6.80s`; Compileall und `git diff --check` sauber.
- [x] Patchversion auf `1.9.488` bumpen und als `d49262ac` committen.
- [ ] Live-Nachweis mit einem realen historischen Fehlereintrag und einer
  aktuell routbaren Adminroute nach Restart pruefen.

### B3. Mehrfach-Queue ohne Route

- [x] Logikfehler reproduzieren: Im `not routable`-Pfad wurde bei mehreren
  zentralen `queued`-Items nur das erste als `deferred` gemeldet.
- [x] Alle zentralen wartenden Items ausgeben, wenn `limit=0` gilt; ein
  positives Limit wird auf die gemeldete Menge angewendet.
- [x] Regression fuer drei wartende Items mit `limit=0` und `limit=2`
  ergaenzen; es gibt weiterhin keinen `dispatch.claim`-/`complete`-Aufruf.
- [x] `pytest -q tests/test_codex_history.py`:
  `160 passed in 7.45s`; History-/Metadaten-Suite:
  `166 passed in 6.89s`; Compileall und `git diff --check` sauber.
- [x] Patchversion auf `1.9.489` bumpen und als `d412df5d` committen.
- [ ] Live-Nachweis mit mehreren zentral wartenden Items ohne private Route
  nach Restart ausfuehren.

### C. Collector-Ressourcen begrenzen

- [ ] Event-Burst- und Pollingpfad getrennt messen.
- [x] Einen abgelaufenen Watchdog-Timeout im `auto`-Modus nicht nochmals als
  zusaetzlichen Schlaf anrechnen.
- [x] Post-Index und Dispatch nicht nach unveraenderten oder reinen Skip-Scans
  erneut ausfuehren.
- [x] Snapshot-Auswahl zwischen Vergleich und Import wiederverwenden.
- [x] Aenderungspfade bis zum Snapshot-Import weiterreichen.
- [x] Bei validierten Datei-Events den Vollsnapshot ueberspringen.
- [x] Watchdog waehrend des gesamten Follow-Laufs offenhalten.
- [x] Watchdog-Lifecycle bei Exceptions schliessen.
- [x] Snapshot-Baseline nach inkrementellen Events aktualisieren.
- [x] Geloeschte/umbenannte Pfade aus der Baseline entfernen.
- [x] Fehlende explizite JSONL-Roots ueber ihren vorhandenen Elternordner
  beobachten, damit spaetere Dateierzeugung nicht verloren geht.
- [x] Start-Exceptions des Watchdogs durch einen geschuetzten `try/finally`-
  Pfad abfangen und einen teilweise gestarteten Observer aufraeumen.
- [x] Stop-/Join-Exceptions best effort behandeln, loggen und den Started-
  Zustand auch bei Cleanup-Fehlern zuruecksetzen.
- [x] Event-Burst-Debounce und Scan-Deduplizierung separat im Watchdog-Test
  pruefen; eine spaet eintreffende zweite Datei wird im gleichen Batch erhalten.
- [x] Read-only Realroot-Vergleich ausfuehren und im Plan dokumentieren.
- [x] Scan-Auswahl-Wiederverwendung mit kleiner Teststruktur pruefen.
- [x] Event-Burst-Debounce mit kleiner reproduzierbarer Teststruktur pruefen.
- [x] Aktuelles Live-Ressourcenprofil aufnehmen: `2.5 GiB RSS`, `95.8 % CPU`,
  rund `31` Scans/10 Minuten und `52 GiB` Prozess-Schreibvolumen seit Start;
  die Nachmessung nach Aktivierung des Fixes bleibt offen.
- [x] Detail-Logs fuer erwartete Altbestand-Skips begrenzen.
- [ ] Eine sichere Default-Grenze fuer Follow-Scans definieren, ohne neue
  Sessions zu verlieren; Grenzwert in Plan und Tests dokumentieren.
- [ ] Code erst nach Messung aendern; danach Collector nur im Restart-Fenster
  neu starten.

### Snapshot-Update: Runtime-Version-Marker

- [x] Laufende Units, MainPIDs und Startzeit schreibfrei erfasst.
- [x] Abweichung zwischen aktuellem Quellstand `1.9.488` und dem vor dem Fix
  gestarteten Live-Prozess dokumentiert.
- [x] Fehlenden Marker als `marker_missing` im Appletstatus bestaetigt.
- [x] Marker-Lifecycle in `TeeBotus/runtime/version_marker.py` und
  `TeeBotus/bot.py` gegen den vorhandenen Start-/Stop-Teststand pruefen; kein
  reproduzierbarer Quellfehler gefunden.
- [ ] Nach dem naechsten erlaubten Restart Marker, PID/Invocation und
  Quellversion live abgleichen.

### D. Weitere actionable Befunde

- [x] Nicht verknuepfte optionale Signal-Identitaet von `Depressionsbot` als
  sichtbaren Hinweis statt Top-Level-Healthfehler klassifizieren; explizites
  Linking bleibt ausschliesslich ueber den bestaetigten Account-Linking-Flow
  erlaubt.
- [ ] Fehlende Provider-Keys nur dann actionable ausweisen, wenn die Route
  aktiviert ist und kein gesunder Fallback wirkt.
- [ ] Matrix-/optionale Slots ohne Credentials als Konfigurationshinweise,
  nicht als Defekt aktiver Telegram-/Signal-Routen anzeigen.

### E. Tests und Live-Abnahme

- [x] Regression lokale queued-Zeile plus zentrale delivered-Zeile.
- [x] Regression zentrale queued-Zeile plus lokale queued-Zeile; ohne
  Empfaenger darf kein zentraler Claim/Complete erfolgen.
- [ ] Regression terminales `no_private_route` mit und ohne routbare
  Adminroute.
- [ ] Regression mehrerer Instanzen mit delegierter Quelle, Logger-Ziel und
  nicht zugelassener Dispatch-Instanz.
- [ ] Applet-Payload/Python-Paritaet mit allen neuen Feldern pruefen.
- [x] Lokalen Collector-Benchmark ohne Provideraufrufe ausfuehren.
- [x] Geaenderten Pfad allein importieren und zweiten Vollscan ausschliessen.
- [x] Race-Regression fuer ein Event waehrend des Imports.
- [x] Exception-Regression fuer Watchdog-Cleanup.
- [x] Timeout-Regression ohne dritten Vollscan.
- [x] Delete-Regression ohne Importfehler und spaeteren Vollscan.
- [x] Regression fuer einen beim Watcher-Start fehlenden expliziten JSONL-Root;
  der Observer wird auf dessen Elternordner angesetzt.
- [x] Regression fuer Watchdog-Start-Exception und Observer-Cleanup.
- [x] Regression fuer fehlgeschlagenes Watchdog-Stop/Join ohne Zustands-Leak.
- [x] Regression fuer malformed Watch-Payloads und String-/Zahlenwerte wie
  `"false"` oder `1`.
- [x] Regression, dass malformed Post-Index-/Dispatch-Ergebnisse den naechsten
  Versuch nicht unterdruecken.
- [x] Regression, dass ein nicht-mappingfaehiger Dispatch-Report den
  Follow-Renderer nicht mehr zum Absturz bringt.
- [x] Regression fuer Import und Eventfilter eines benutzerdefinierten Roots
  ohne Pfadsegment `sessions`, bei Erhalt des Agentenroot-Schutzes.
- [x] Regression fuer Burst-Koaleszenz: doppelte Pfade werden entfernt,
  unterschiedliche Pfade bleiben erhalten und die Queue wird geleert.
- [x] Lokalen Burst-Benchmark ohne Provideraufrufe ausfuehren.
- [x] Applet-Topanzeige mit actionable Account-Identitaetswarnung und
  verifiziertem Fallback pruefen.
- [x] Regression fuer begrenzte Follow-Detailausgabe.
- [x] Regression fuer den inkrementellen Ereignispfad.
- [ ] Collector-Debounce-/Ressourcenbenchmark mit grossem Sessionroot.
- [ ] Runtime-Status, Applet-Health und Dispatcher-Snapshot nach dem naechsten
  erlaubten Restart erneut vergleichen.

## Abnahmekriterien

Der Plan ist erst abgeschlossen, wenn:

1. jede actionable Applet-Warnung eine konkrete reproduzierbare Ursache oder
   eine bestaetigte Konfigurationsaktion besitzt;
2. TBL-lokale `queued`-/`skipped`-Zeilen eindeutig als offen, terminal,
   historisch oder korrupt klassifiziert sind;
3. keine zentrale `delivered`-/`compacted`-Information im lokalen Spiegel als
   offene Zustellung erscheint;
4. keine noch nicht zugestellte Summary durch Reconciliation verloren oder
   geloescht werden kann;
5. der Follow-Collector unter realistischem Sessionbestand mit begrenztem
   CPU-/Speicherverbrauch stabil laeuft;
6. fokussierte und relevante Volltests gruen sind und hier vermerkt wurden;
7. Quellstand, lokaler Commit und Live-Nachweis dokumentiert sind.

## Nachweisprotokoll

- 2026-07-13: Dieser neue kanonische Bauplan wurde aus dem aktuellen aktiven
  Arbeitsstand erstellt.
- 2026-07-13: Lokale Statusprobe bestaetigte `queued=0`, `delivered=26`,
  `compacted=310`, `total=336` und leeres `last_error` im zentralen Dispatcher.
- 2026-07-13: Lokale TBL-Probe bestaetigte queued-/Skip-Reste und eine routbare
  Telegram-Adminroute.
- 2026-07-13: Applet-Probe bestaetigte genau einen actionable Befund wegen der
  fehlenden Signal-Identitaetsverknuepfung von `Depressionsbot`.
- 2026-07-13: Die Watchdog-/Snapshot-/Import-Reconciliation wurde in den
  Commits `11496d09`, `58c9a3f9`, `6934413e`, `e2aef4cb`, `b03738df`,
  `afdbf53b`, `0859d7d8` und `d55594bf` schrittweise repariert.
- 2026-07-13: `pytest -q tests/test_codex_history.py tests/test_pyproject_metadata.py`
  erfolgreich: `145 passed in 7.23s`.
- 2026-07-13: Ruff meldete nur die bekannten neun E402-Befunde am bestehenden
  optionalen `fcntl`-Import; keine neuen Befunde in den geaenderten Pfaden.
- 2026-07-13: Read-only Realroot-Vergleich mit 1000 Dateien ausgefuehrt:
  Snapshot `2303.15 ms`, Eventfilter `0.5543 ms`, Baseline-Update `0.7585 ms`,
  ohne Provider- oder Netzwerkanfragen.
- 2026-07-13: Lokaler Poll-Benchmark ohne Provideraufrufe ausgefuehrt:
  10 Dateien, 10 Iterationen, `262.27 ms`, `38.13 Operationen/s`,
  `network_calls=0`.
- 2026-07-13: Logikfehler bei fehlenden expliziten JSONL-Roots behoben:
  `cf5ef12f` (`1.9.473`) beobachtet jetzt den Elternordner statt eines beim
  Start nicht vorhandenen Dateipfads. Die fokussierten Watcher-Tests liefen
  mit `6 passed`; die Codex-History- und Metadaten-Suite mit `146 passed in
  7.68s`. Compile- und `git diff --check`-Pruefung waren ebenfalls sauber.
- 2026-07-13: Lifecycle-Logikfehler bei einem fehlgeschlagenen Watchdog-Start
  behoben: `66e040a6` (`1.9.474`) fuehrt den Start in den aeusseren
  `try/finally`-Pfad und raeumt einen teilweise gestarteten Observer best
  effort auf. Die fokussierten Watchdog-Tests liefen mit `8 passed`; die
  Codex-History- und Metadaten-Suite mit `148 passed in 6.52s`.
- 2026-07-13: Cleanup-Logikfehler bei fehlgeschlagenem Stop/Join behoben:
  `c0ce4201` (`1.9.475`) versucht beide Schritte best effort, protokolliert
  beide Fehler und setzt den internen Zustand garantiert zurueck. Die
  Codex-History- und Metadaten-Suite lief mit `149 passed in 7.10s`.
- 2026-07-13: Health-Logikfehler in `_watch_payload_ok` behoben:
  `75779b78` (`1.9.476`) lehnt malformed Reports sowie String-/Zahlenwerte fuer
  `ok` fail-closed ab. Die fokussierten Payload-Tests liefen mit `6 passed`; die
  Codex-History- und Metadaten-Suite mit `154 passed in 8.88s`.
- 2026-07-13: Retry-Logikfehler im Watch-Post-Index-/Dispatch-Gate behoben:
  `6d306f50` (`1.9.477`) setzt Pending nur noch bei strikt `ok=True` zurueck
  und bewahrt malformed Reports fuer den naechsten Versuch. Die fokussierten
  Tests liefen mit `10 passed`; die Codex-History- und Metadaten-Suite mit
  `157 passed in 7.10s`.
- 2026-07-13: Folgefehler bei malformed Follow-Reports behoben:
  `f7ad74a2` (`1.9.478`) normalisiert nicht-mappingfaehige Post-Index- und
  Dispatch-Ergebnisse vor Speicherung und Ausgabe. Die fokussierten Tests
  liefen mit `11 passed`; die Codex-History- und Metadaten-Suite mit
  `158 passed in 6.64s`.
- 2026-07-13: Root-Logikfehler behoben: `6b360544` (`1.9.479`) akzeptiert
  direkte JSONL-Dateien in benutzerdefinierten Sessionroots und verwendet den
  gleichen Filter fuer Watchdog-Events. Ein Agentenroot mit eigener
  `sessions`-Unterstruktur scannt weiterhin keine fremden Fixture-JSONL.
  Die fokussierten Tests liefen mit `14 passed`; die Gesamtsuite mit
  `159 passed in 5.85s`.
- 2026-07-13: Event-Burst-Verhalten verifiziert; `3374e6eb` ergaenzt die
  Regression fuer Deduplizierung und Pfaderhalt. Ein lokaler Benchmark mit
  `10000` Events und `100` eindeutigen Pfaden ergab `166.543 ms`,
  `60044.5 Events/s` und `network_calls=0`. Die Gesamtsuite lief mit
  `160 passed in 6.70s`; ein weiterer Produktionslogikfehler wurde dabei
  nicht reproduziert.
- 2026-07-13: Bridge-Verlustpfad behoben: Ohne gueltige Admin-Empfaenger
  fuehrt der TeeBotus-Bridge-Worker keinen zentralen `dispatch.claim` und
  keinen leeren `dispatch.complete` mehr aus. Solche Items bleiben zentral
  `queued` und werden als `deferred/no_recipient_accounts` sichtbar. Bereits
  terminale zentrale Zustaende duerfen weiterhin lokal synchronisiert werden.
  Die lokale Reconciliation liest nach dem Mirror den aktuellen Store erneut,
  damit keine doppelten Statushistorien entstehen. Patchstand `1.9.480`.
- 2026-07-13: `pytest -q tests/test_codex_history.py tests/test_pyproject_metadata.py`
  erfolgreich: `160 passed in 7.22s`; Compileall und `git diff --check` sauber.
- 2026-07-13: Der Plan bleibt bis zur TBL-Reconciliation, der Event-Burst-/
  Ressourcenmessung und der naechsten erlaubten Live-Abnahme aktiv.
- 2026-07-13: Applet-Health-Detail-Fix in `1.9.481`: Die obere Anzeige nennt
  die konkrete Ursache `Signal-Verknuepfung Depressionsbot erforderlich`;
  Fallbacks mit `effective_status=configured` werden dort nicht als actionable
  Ursache wiederholt. `pytest -q tests/test_cinnamon_applet.py` erfolgreich:
  `231 passed in 37.28s`.
- 2026-07-13: Bridge-Logikfehler in `1.9.482` behoben: Eine konfigurierte
  Admin-ID ohne aktuelle private Route durfte zuvor trotzdem zentral geclaimt
  und als terminales `skipped/no_private_route` abgeschlossen werden. Ein
  schreibfreier Route-Preflight lässt solche Items jetzt zentral `queued` und
  meldet sie als `deferred/no_private_route`; echte routbare Empfaenger gehen
  unveraendert durch den Claim-/Complete-Pfad. Die fokussierte Bridge-/Shadow-
  Suite lief mit `25 passed`, die History-/Metadaten-Suite mit `161 passed`;
  Compileall und `git diff --check` waren sauber.
- 2026-07-13: Neuer Applet-Arbeitsschritt begonnen: lokale TBL-Bridge-Queue
  und zentrale Dispatcher-Queue werden im Projekt-History-Menue getrennt
  benannt. Der Patch ist im Arbeitsbaum vorhanden, aber noch nicht installiert
  oder committed; die fokussierten Tests liefen mit `6 passed`. Ein kompletter
  Applet-Lauf hatte einmal den bestehenden Timeout-Test als intermittierenden
  PID-/Reaping-Race markiert; der isolierte Wiederholungslauf lief mit
  `1 passed`. Vollsuite, Installation und Commit bleiben offen.
- 2026-07-13: Applet-Queue-Anzeigepatch in `1.9.483` verifiziert: Die lokale
  Bridge-Outbox und die zentrale Dispatcher-Queue werden getrennt und mit
  unterschiedlichen Zustandsbegriffen angezeigt. Die komplette Suite lief
  mit `232 passed in 38.22s`; die lokale Installation wurde erfolgreich
  aktualisiert und `diff -qr` meldete Quell-/Installationsparitaet. Der
  bestehende Timeout-Test war im isolierten Wiederholungslauf sowie im letzten
  Vollauf erfolgreich; kein Produktionscode wurde dafuer geaendert. Der
  Funktionsstand ist als `7b6da19a` committed, die Metadaten-Suite lief mit
  `6 passed in 0.07s`.
- 2026-07-13: Follow-Collector-Logikfehler in `1.9.484` behoben: Der
  Watchdog koalesziert JSONL-Event-Bursts bis `0.25 s` und maximal `2.0 s`;
  damit erzeugt ein laufender Stream nicht mehr fuer jedes Einzelereignis
  einen erneuten Vollpfad. Die persistierte History bleibt vollstaendig,
  waehrend der langlebige Follow-Report nur noch 24 Diagnoseobjekte im RAM
  behaelt. Fokussiert liefen `42 passed in 3.79s`, die History-/Metadaten-
  Suite mit `162 passed in 9.50s`; die fokussierte Wiederholung lief mit
  `42 passed in 2.26s`. Ein synthetischer Burst mit `101` Ereignissen ergab
  `101` eindeutige Pfade in einem Batch, `784.2 ms` und
  `network_calls=0`. Die Metadaten-Suite lief mit `6 passed in 0.07s`.
  Der Funktionsstand ist als `409206a3` committed. Live-Restart und
  Nachmessung bleiben wegen der Restart-Grenze offen.
- 2026-07-13: Follow-Collector-Logikfehler in `1.9.485` behoben: Der
  Watchdog verarbeitete zuvor jedes `on_any_event`, einschliesslich
  `opened`/`closed_no_write`; das konnte durch die eigenen Lesezugriffe einen
  Selbsttrigger verursachen. Eine Mutations-Allowlist filtert reine
  Leseereignisse. Fokussiert liefen `42 passed in 3.68s`, die
  History-/Metadaten-Suite mit `162 passed in 8.11s`; Compileall und
  `git diff --check` waren sauber. Der Funktionsstand ist als `96523652`
  committed. Die Live-Ressourcenmessung nach Restart bleibt offen.
- 2026-07-13: Follow-Collector-Logikfehler in `1.9.486` behoben: Der
  Eventfilter ermittelte zuvor bei jedem Batch die bis zu 301 verschachtelten
  Sessionroots erneut. Der Watcher verwendet jetzt einen Cache und erneuert
  ihn nur bei einem unbekannten, noch vorhandenen Eventpfad. Die Auswahl bleibt
  identisch, aber der echte Eventfilter fiel von `1963.8 ms` auf `0.988 ms`.
  Watcher-Fokus: `43 passed in 3.52s`; History-/Metadaten-Suite:
  `163 passed in 7.46s`; Compileall und `git diff --check` sauber. Live-
  Restart und Ressourcen-Nachmessung bleiben offen. Der Funktionsstand ist
  als `1fced73f` committed.
- 2026-07-13: Neue Plan-Momentaufnahme fuer die Logikfehlerpruefung erstellt.
  Read-only Systemd-Pruefung bestaetigte, dass beide laufenden Units noch seit
  `06:41:32 CEST` auf dem Prozessstand vor `1.9.486` laufen. Der Runtime-
  Versionsmarker fehlt; Lifecycle-Pruefung und Live-Nachmessung bleiben deshalb
  offen. Es wurde kein Restart und kein Push ausgeloest.
- 2026-07-13: Marker-Ursache weiter eingegrenzt: `INVOCATION_ID` ist in beiden
  Units gesetzt, das Journal meldet aber noch den alten Runtime-/Notification-
  Stand `1.9.404`. `marker_missing` ist deshalb erwarteter Versionsdrift und
  kein belegter Fehler des aktuellen Marker-Lifecycles. Live-Matching nach
  Restart bleibt als Nachweis offen.
- 2026-07-13: Bridge-Logikfehler im Mixed-Route-Fall behoben: Obwohl der
  Preflight `routable_account_ids` berechnete, wurde zuvor die vollstaendige
  Kandidatenliste versendet. `1.9.487` verwendet jetzt nur die routbare
  Teilmenge. Regression und History-/Metadaten-Suite liefen mit `164 passed in
  6.95s`; Commit `5c6992dc`. Kein Restart und kein Push ausgeloest.
- 2026-07-13: Bridge-Logikfehler bei stale Recipient-Results behoben: Ein
  alter `failed`-Empfaenger ausserhalb der aktuellen routbaren Menge wird beim
  naechsten Retry als `skipped/recipient_not_routable` weitergegeben, damit
  eine erfolgreiche aktuelle Route nicht global als `failed`/`queued` blockiert
  bleibt. Version `1.9.488`, Commit `d49262ac`; `158` History-Tests und `164`
  History-/Metadaten-Tests gruen. Kein Restart und kein Push ausgeloest.
- 2026-07-13: Bridge-Logikfehler im `no_private_route`-Mehrfachfall behoben:
  Der Pfad meldet jetzt alle wartenden zentralen Items bei `limit=0` und
  respektiert ein positives Limit, statt nur das erste Item zu zeigen. Version
  `1.9.489`, Commit `d412df5d`; `160` History-Tests und `166`
  History-/Metadaten-Tests gruen. Kein Restart und kein Push ausgeloest.
- 2026-07-13: Eine konfigurierte, aber noch nicht sicher verknuepfte
  Signal-Identitaet wird als `account_identity_notice` statt als actionable
  Top-Level-Warnung gemeldet. Die Quellprobe ergab `health.status=ok`,
  `actionable_problem_count=0` und eine sichtbare Notice. Automatisches
  Linking bleibt aus Sicherheitsgruenden verboten; der bestaetigte
  `/login`-Flow bleibt die einzige Aktion.
- 2026-07-15: Live-Healthcheck reproduzierte einen echten, aber operativen
  Befund: `teebotus.service` war seit 21:06 CEST sauber mit `SIGTERM` beendet
  (`Result=success`), nicht abgestuerzt. Deshalb waren die Signal-Service- und
  Signal-Account-Probes `unreachable`/`unavailable`; `Restart=on-failure` darf
  einen absichtlichen Stop nicht selbststaendig aufheben. Dienst wurde wieder
  gestartet. Neue Applet-Probe: `health.status=ok`, `command_ok=true`,
  `actionable_problem_count=0`, `total_problem_count=0`, Qdrant-Fehler `0`,
  Unit `active/running`.
- Die verbleibenden `20` Hinweise sind nicht-actionable und nachvollziehbar:
  Gemini-Limitquelle nutzt konservative Defaults (`1`), zwei optionale
  fehlende Provider-Keys, drei partielle Offload-Zustaende, sieben erklaerte
  Fallback-/Pool-Hinweise und sieben bekannte Codex-Usage-/History-Hinweise.
  Der Applet-Header darf sie als Hinweise zeigen, aber nicht als `Health
  defekt` bewerten. Keine Applet-Codeaenderung war dafuer erforderlich.
