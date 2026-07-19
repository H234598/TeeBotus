# Bauplan: Healthcheck-/Applet-Warnungsabbau und Codex-History-Reconciliation

**Stand:** 2026-07-13  
**Status:** Aktiv, noch nicht abgeschlossen  
**Quellstand:** TeeBotus `1.9.472`, lokaler Folgecommit nach `0859d7d8`
**Geltungsbereich:** Runtime-Healthcheck, TeeBotus-Cinnamon-Applet, TBL-Adminstatus, Codex-History-Bridge und Collector-Performance

## Auftrag

Die Warnungen und Probleme, die oben im TeeBotus-Applet erscheinen, werden
bis zu ihrer technischen Ursache verfolgt. Echte Betriebsprobleme muessen
sichtbar und handlungsrelevant bleiben. Reine Hinweise, delegierte Quellen,
terminale Nichtzustellungen und bekannte Fallbacks duerfen nicht als Defekt
erscheinen, muessen aber in der Detaildiagnose erhalten bleiben.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Dieser neue Bauplan fasst den aktuellen Planstand fuer die noch offenen
Healthcheck-/Applet-Themen zusammen. Die bisherigen Detailplaene bleiben als
Nachweis bestehen:

- `Abgeschlossene Baupläne/Bauplan-Aktueller-Planstand-Healthcheck-Warnungen-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Healthcheck-Applet-Aktuelle-Logikpruefung-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Arbeitsstand-Logikpruefung-Codex-History-2026-07-13.md`

## Leitplanken

- Sicherheit vor Bequemlichkeit: unbekannte, widerspruechliche oder nicht
  authentisierte Zustaende werden nicht als gesund behandelt.
- Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer Diagnose,
  Reconciliation oder Tests.
- Healthcheck, Status-Applet und Dry-Runs lesen nur. Linking, Requeue,
  Status-Reconciliation, Quarantaene und Konfigurationsaenderungen bleiben
  explizite, nachvollziehbare Aktionen.
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
  Fallback wird nicht mehr unnoetig als Top-Level-Defekt gewertet.
- Unbekannte oder widerspruechliche Statuswerte werden nicht still als `ok`
  behandelt.
- Quell- und installierte Applet-Kopie waren zuletzt byte-identisch.

### Secret-Service- und Adminstatus

- Normale Runtime-Statuspfade verwenden die runtime-konfigurierte
  Secret-Service-Retry-/Timeout-Policy.
- Read-only-Adminlookup verwendet dieselbe Retry-/Timeout-Policy.
- Der Memory-Recovery-Pfad behaelt bewusst seinen separaten read-only Provider,
  damit alte oder defekte Verschluesselungsmetadaten diagnostizierbar bleiben.

### Codex-History-Bridge

- Der zentrale `history-dispatcher.service` laeuft im Bridge-Modus.
- Der zentrale Dispatcher ist read-only nachgewiesen mit:
  `queued=0`, `delivered=26`, `compacted=310`, `total=336`, leerem
  `last_error`.
- TBL besitzt eine routbare Telegram-Adminroute auf Slot 1.
- Delegierte Codex-History-Quellen werden im Bridge-Modus nicht als lokale
  Fehler hochgestuft.
- Der Bridge-Pfad gleicht nach einem leeren `dispatch.claim` die lokalen
  dispatchierbaren Zeilen nochmals mit dem zentralen `history.query` ab.
  Eindeutig gematchte terminale Dispatcher-Zustaende werden idempotent in die
  lokale Outbox uebernommen. Dabei werden keine lokalen Zeilen geloescht,
  nicht erneut zugestellt und keine Recipient-Resultate erfunden.

## Aktueller Live-Befund

### Applet-Health nach dem Patch

Eine direkte Probe mit `python -m TeeBotus.cinnamon_applet status` ergibt
aktuell:

```text
health.status=warning
health.actionable_problem_count=1
health.informational_problem_count=23
health.runtime_problem_count=1
health.qdrant_problem_count=0
command_ok=true
```

Der einzige actionable Befund ist:

```text
account_identity_warning=Depressionsbot code=runtime_channel_without_identity
channel=signal configured_runtime_slots=1 identity_channels=telegram:3
```

Das ist kein Applet- oder Parserfehler. Der Signal-Runtime-Slot ist fuer
`Depressionsbot` konfiguriert und erreichbar, aber noch keiner bestehenden
Signal-Identitaet zugeordnet. Ohne explizites Account-Linking wuerde ein
Signal-Eingang einen separaten Account verwenden. Der Zustand bleibt deshalb
bewusst handlungsbeduerftig; automatisches Linken waere eine unzulaessige
Account-/Sicherheitsmutation.

Die installierte Cinnamon-Datei
`~/.local/share/cinnamon/applets/teebotus@H234598/applet.js` ist byte-identisch
mit `files/teebotus@H234598/applet.js` (SHA-256 `9a105af5d2c1c0e6dbfb1c88825991ac0d04cef4f9109d2e4da070b6509733b0`).
Ein altes Applet ist damit als Ursache ausgeschlossen. Die 23 weiteren
Statusbefunde werden durch die Klassifikation als Hinweise angezeigt:
optionale Fallbacks, fehlende optionale Keys, unvollstaendige Codex-Usage-
Snapshots und bekannte `no_private_route`-History-Skips.

### TBL-Codex-History

Die lokale TBL-Statusaggregation zeigt aktuell sinngemaess:

```text
codex_history=TeeBotus_Logger status=warning queued=122 failed=0 total=1591
skipped=101 problem_statuses=queued:122,skipped:101
skip_reasons=no_private_route:101
```

Auf Repository-Ebene liegen die `queued`-Eintraege vor allem in den
Historien von `codex-usage` und `TeeBotus`; weitere Repositories enthalten
terminale `no_private_route`-Skips. Gleichzeitig ist der zentrale Dispatcher
leer und hat bereits 336 zentrale Items terminal verarbeitet.

Damit sind mindestens zwei Datenzustaende zu unterscheiden:

1. **Zentrale Dispatcher-Wahrheit:** keine wartende zentrale Queue, kein
     letzter Dispatcherfehler.
2. **Lokale TBL-Spiegelung:** viele alte `queued`-Zeilen und terminale
   `no_private_route`-Resultate.

Der Status ist deshalb noch nicht als reiner Parserfehler einzustufen. Es ist
offen, ob die lokalen TBL-Zeilen historische Legacy-/Spiegelreste sind oder
ob bei der Bridge-Reconciliation lokale Terminalstatus nicht nachgezogen
werden.

### Routing und Instanzen

- `TeeBotus_Logger` ist fuer Codex-History-Dispatch zugelassen.
- Der TBL-Adminaccount ist laut Runtime-Status routbar: Telegram, Slot 1,
  Quelle `TeeBotus_Logger`.
- `Bote_der_Wahrheit` und `Depressionsbot` erscheinen als delegierte
  Bridge-Quellen; ihre lokalen `queued`-Zaehler sind deshalb nicht automatisch
  ein Zustellfehler.
- Matrix-Slots ohne Matrix-Credentials sowie nicht verknuepfte optionale
  Signal-Slots bleiben getrennte Hinweise. Eine Telegram-Identitaet darf nicht
  automatisch als Signal-Identitaet verknuepft werden.

### Collector-Performance

Der laufende Follow-Collector ist aktiv, zeigt aber einen auffaelligen
Ressourcenverbrauch: zuletzt etwa 1.9 GiB RSS und rund 96 Prozent CPU. Obwohl
`--poll-interval 300` gesetzt ist, loesen Dateisystemereignisse wiederholte
Scans aus. In den Logs erscheinen ausserdem viele erwartete Import-Skips wegen
`missing_final_text` und `invalid_repo_root`.

Das ist ein eigener Health-/Betriebsbefund und darf nicht mit der TBL-Queue
vermischt werden. Vor einer Optimierung muss geklaert werden, ob die Last aus
Event-Burst-Debouncing, wiederholtem Lesen grosser Accountstores, Export,
Qdrant-Indexierung oder einer Kombination entsteht.

Der erste konkrete Performancefehler ist jetzt reproduziert und behoben: Im
Snapshot-/Auto-Watcher wurde die bereits fuer den Snapshot ermittelte Liste
der Sessiondateien beim anschliessenden Import nochmals rekursiv gesucht und
sortiert. Der Watcher reicht diese Auswahl nun direkt an den Import weiter.
Der Poll-Modus bleibt unveraendert; bei mehreren Instanzen wird dieselbe
read-only Dateiauswahl bewusst wiederverwendet.

Der zweite konkrete Fehler lag im Ereignispfad: Ein einzelnes JSONL-Ereignis
loeste bislang den Import der kompletten Auswahl von bis zu 1000 Sessiondateien
aus. Der Watchdog reicht nun die geaenderten JSONL-Pfade zurueck. Der Snapshot
bleibt als Konsistenzpruefung bestehen, aber der Import verarbeitet bei einem
reinen Datei-Update nur die betroffenen, noch vorhandenen Pfade.

Auch die Follow-Textausgabe war ungebunden: Bei vielen erwarteten
`missing_final_text`-Skips wurde jeder Detailpfad ins Journal geschrieben.
Die Statuszaehler bleiben vollstaendig; pro Instanz werden aber hoechstens 12
Nicht-Duplicate-Details ausgegeben und die Zahl der ausgelassenen Details wird
explizit vermerkt.

Der Ereignispfad benoetigte ausserdem bislang trotz bekanntem Watchdog-Pfad
noch einen vollstaendigen Metadaten-Snapshot. Bei einem validierten
Dateiereignis wird dieser Snapshot jetzt uebersprungen; ein Vollsnapshot bleibt
fuer den Erstlauf und den Timeout-/Fallbackpfad erhalten. Ereignispfade werden
gegen die konfigurierten Sessionroots geprueft und geloeschte Dateien nicht
inkrementell importiert.

Der Watchdog bleibt nun waehrend des gesamten Watch-Laufs aktiv. Dadurch
werden JSONL-Aenderungen, die waehrend Import, Post-Index oder Dispatch
eintreffen, nicht bis zum naechsten Timeout verschluckt. Die aufgelaufenen
Pfade werden am naechsten Wartepunkt abgeholt; ein Timeout laesst weiterhin den
konservativen Vollsnapshot laufen.

Der Watchdog-Lifecycle ist jetzt auch bei Fehlern geschlossen: Der oeffentliche
Watcher injiziert den Observer in die Schleife und beendet ihn in einem
`finally`-Pfad. Ein Fehler aus Import oder Callback kann dadurch keinen
verwaisten Observer-Thread zuruecklassen.

Nach einem inkrementellen Event wird die Snapshot-Baseline nun fuer die
betroffenen Pfade anhand von `stat` aktualisiert. Dadurch interpretiert der
naechste Timeout den bereits verarbeiteten Event nicht erneut als Aenderung und
startet keinen unnoetigen Vollimport.

Auch geloeschte oder umbenannte Quellpfade werden fuer die Baseline
beruecksichtigt, ohne sie erneut importieren zu wollen. Damit bleibt ein
entfernter Pfad nicht bis zum naechsten Timeout als scheinbar aktuelle Datei
erhalten.

## Offene Arbeitspakete

### A. TBL-Reconciliation schreibfrei beweisen

- [ ] Lokale TBL-Outbox, lokale Dispatch-Results und zentrale
  `history_items`/`recipient_results` ueber Item-ID und Dedupe-Key abgleichen.
- [ ] Fuer jede lokale `queued`-Zeile feststellen: zentral nicht vorhanden,
  zentral terminal, zentral weiterhin queued oder nur lokale Legacy-Zeile.
- [ ] Fuer jeden `no_private_route`-Skip pruefen, ob zum Zeitpunkt des Skips
  wirklich keine gueltige private Route existierte.
- [ ] Ergebnis als JSON/Markdown-Report speichern, ohne Daten zu veraendern.
- [ ] Erst nach Review einen idempotenten Reconciliation-Befehl bauen, der
  nur eindeutig zentral bestaetigte terminale Status lokal nachtraegt.

### B. Bridge-Dispatchfluss reparieren oder entwarnen

- [ ] Den Watcher-Dispatch pro Instanz getrennt ausgeben und pruefen, ob
  `TeeBotus_Logger` tatsaechlich `dispatch.claim` und `dispatch.complete`
  erreicht.
- [ ] Pruefen, ob `dispatch statuses: none` nur bedeutet, dass kein neuer
  lokaler Kandidat vorliegt, oder ob ein Statusreport verworfen wird.
- [x] Sicherstellen, dass zentrale terminale Ergebnisse idempotent in den
  lokalen TBL-Spiegel geschrieben werden, wenn nach dem Claim kein neuer
  zentraler Claim vorliegt.
- [ ] Keine pauschale Requeue-Aktion fuer alte `queued`-Zeilen. Requeue nur
  fuer nachweislich nicht zugestellte, noch gueltige Eintraege.
- [ ] Den Applet-Healthstatus so erweitern, dass zentrale Queue `0` und lokale
  historische Spiegelreste getrennt benannt werden.

### C. Collector-Ressourcenverbrauch begrenzen

- [ ] Event-Burst und Pollingpfad getrennt messen.
- [x] Verhindern, dass ein bereits abgelaufener Watchdog-Timeout im
  `auto`-Modus nochmals als zusaetzlicher Schlaf angerechnet wird.
- [x] Post-Index und Dispatch nicht nach jedem unveraenderten oder nur
  uebersprungenen Scan erneut ausfuehren. Der erste Scan wird weiterhin
  verarbeitet; danach triggern echte neue Importe den teuren Nachlauf.
- [x] Snapshot-Dateiauswahl zwischen Zustandsvergleich und Import wiederver-
  wenden; dadurch entfaellt der zweite rekursive Sessionroot-Scan pro
  veraendertem Snapshot.
- [x] Watchdog-Aenderungspfade bis zum Snapshot-Import weiterreichen; ein
  einzelnes JSONL-Ereignis verarbeitet nicht mehr die gesamte `limit`-Menge.
- [x] Bei validierten Watchdog-Ereignissen den zusaetzlichen Vollsnapshot
  ueberspringen; Erstlauf und Timeout-Fallback behalten die Snapshot-Pruefung.
- [x] Watchdog ueber den gesamten Follow-Lauf offenhalten, damit Events
  waehrend Import/Post-Index nicht bis zum Timeout verloren gehen.
- [x] Watchdog-Lifecycle bei Scan-/Callback-Exceptions ueber einen aeusseren
  Cleanup-Pfad garantieren.
- [x] Snapshot-Baseline nach inkrementellen Events aktualisieren, damit der
  folgende Timeout nicht nochmals alle bekannten Dateien importiert.
- [x] Geloeschte/umbenannte Eventquellen aus der Baseline entfernen, aber nur
  noch vorhandene Dateien inkrementell importieren.
- [ ] Event-Burst-Debounce und Scan-Deduplizierung separat messen; ein
  Dateisystemereignis darf weiterhin zeitnah erkannt werden, aber nicht zu
  unnoetigen Vollscans fuer jede einzelne JSONL-Aenderung fuehren.
- [x] Read-only Realroot-Vergleich ausgefuehrt: 1000-Datei-Snapshot
  `2303.15 ms`, Eventpfad-Filter `0.5543 ms`, Baseline-Update `0.7585 ms`;
  keine Provider- oder Netzwerkanfragen.
- [x] Scan-Auswahl-Wiederverwendung anhand einer kleinen reproduzierbaren
  Sessionroot-Teststruktur pruefen.
- [ ] Event-Burst-Debounce anhand einer kleinen reproduzierbaren Sessionroot-
  Teststruktur pruefen.
- [ ] Speicherprofil fuer Session-Import, Accountstore-Lesen, Post-Index und
  Dispatch aufnehmen.
- [x] `missing_final_text` und `invalid_repo_root` bounded loggen, damit ein
  grosser Altbestand den Journal- und CPU-Pfad nicht mit Detailzeilen
  ueberlaedt; vollstaendige Statuszaehler bleiben erhalten.
- [ ] Eine sichere Default-Grenze fuer Follow-Scans definieren, ohne neue
  Sessions zu verlieren; Grenzwert muss im Plan und in Tests dokumentiert
  werden.
- [ ] Erst nach Messung Code aendern; danach Collector nicht ausserhalb der
  Restart-Regel neu starten.

### D. Uebrige actionable Befunde

- [ ] Nicht verknuepfte optionale Signal-Identitaet des Depressionsbots nur
  ueber den bestaetigten Account-Linking-Flow pruefen.
- [ ] Fehlende LLM-/Provider-Keys nur dann als actionable ausweisen, wenn die
  betreffende Route wirklich aktiviert und kein gesunder Fallback wirksam ist.
- [ ] Matrix-/optionale Slots ohne Credentials als konfigurationsbezogene
  Hinweise anzeigen, nicht als Defekt der aktiven Telegram-/Signal-Routen.

### E. Tests und Live-Abnahme

- [x] Regression fuer lokale queued-Zeile plus zentrale delivered-Zeile.
- [ ] Regression fuer zentrale queued-Zeile plus lokale queued-Zeile.
- [ ] Regression fuer terminales `no_private_route` mit und ohne aktuell
  routbarer Adminroute.
- [ ] Regression fuer mehrere Instanzen: delegierte Quelle, Logger-Ziel und
  nicht zugelassene Dispatch-Instanz.
- [ ] Applet-Payload/Python-Paritaet mit allen neuen Feldern pruefen.
- [x] Lokalen Collector-Benchmark ohne Provideraufrufe ausfuehren:
  `codex_history_watcher_poll_loop`, 10 Sessiondateien, 10 Iterationen,
  `ok=true`, 262.27 ms, 38.13 Operationen/s, `network_calls=0`.
- [x] Regression pruefen, dass ein geaenderter Pfad allein importiert wird;
  der Test endet mit drei Importen statt einem zweiten Vollscan mit
  Duplicate-Ergebnissen.
- [x] Race-Regression fuer ein Event waehrend des Imports; der Pfad wird im
  folgenden Lauf sofort verarbeitet.
- [x] Exception-Regression: ein fehlgeschlagener Scan beendet den Watchdog
  trotzdem.
- [x] Timeout-Regression: Eventlauf plus anschliessender Timeout bleibt bei
  zwei Imports und erzeugt keinen dritten Vollscan.
- [x] Delete-Regression: geloeschtes Event erzeugt keinen Importfehler und
  keinen spaeteren Vollscan.
- [x] Regression fuer begrenzte Follow-Detailausgabe: 15 Skips ergeben 12
  Detailzeilen, eine Auslassungszeile und weiterhin `skipped=15`.
- [x] Regression fuer den inkrementellen Ereignispfad: ein geaenderter
  Sessionpfad fuehrt nur zu einem Snapshot-Aufruf im Zweilauf-Test.
- [ ] Collector-Debounce-/Ressourcenbenchmark mit realistischem grossem
  Sessionroot ausfuehren.
- [ ] Runtime-Status, Applet-Health und Dispatcher-Snapshot nach dem naechsten
  erlaubten Restart erneut vergleichen.

## Abnahmekriterien

Der Plan ist erst abgeschlossen, wenn:

1. jede actionable Applet-Warnung auf eine konkrete, reproduzierbare Ursache
   oder eine bestaetigte Konfigurationsaktion zurueckgeht;
2. TBL-lokale `queued`-/`skipped`-Zeilen eindeutig als offen, terminal,
   historisch oder korrupt klassifiziert sind;
3. keine zentrale `delivered`-/`compacted`-Information durch den lokalen
   Spiegel als offene Zustellung erscheint;
4. keine noch nicht zugestellte Summary durch Reconciliation verloren oder
   geloescht werden kann;
5. der Follow-Collector unter realistischem Sessionbestand stabil und mit
   begrenztem CPU-/Speicherverbrauch laeuft;
6. fokussierte und relevante Volltests gruen sind und ihre Ergebnisse hier
   vermerkt wurden;
7. der aktuelle Quellstand, lokale Commit-ID und Live-Nachweis dokumentiert
   sind.

## Nachweisprotokoll

- 2026-07-13: Neuer Sammelbauplan angelegt.
- 2026-07-13: Read-only-Liveprobe bestaetigte zentralen Dispatcher mit
  `queued=0`, `delivered=26`, `compacted=310`, `total=336` und leerem
  `last_error`.
- 2026-07-13: Read-only-Liveprobe bestaetigte TBL lokal mit queued-/Skip-
  Resten sowie routbarer Telegram-Adminroute.
- 2026-07-13: Collector als aktiv, aber ressourcenauffaellig beobachtet;
  weitere Messung ist offen.
- 2026-07-13: Konkreten Bridge-Logikfehler behoben: Ein externer Dispatcher
  konnte eine Summary zwischen `history.append` und dem naechsten Lauf
  terminal verarbeiten; bei leerem `dispatch.claim` blieb die lokale Spiegelung
  trotzdem auf `queued`. Der Bridge-Lauf fragt in diesem Fall den zentralen
  Bestand ab und synchronisiert nur eindeutig gematchte terminale Statuswerte.
- 2026-07-13: `pytest -q tests/test_codex_history.py` erfolgreich: `131 passed`
  in `8.55s`. Der neue Regressionstest prueft den Ablauf
  `history.append -> dispatch.claim (leer) -> history.query -> lokal delivered`;
  Orphan- und Mirror-Fehler bleiben weiterhin queued bzw. failed sichtbar.
- 2026-07-13: Live-Appletprobe mit TeeBotus `1.9.462`: `command_ok=true`,
  Qdrant-/Unit-Fehler `0`, genau ein actionable Health-Befund wegen der
  fehlenden Signal-Identitaetsverknuepfung von `Depressionsbot`; die
  installierte Applet-Kopie ist byte-identisch zur Repo-Kopie.
- 2026-07-13: Wartepfad-Logikfehler behoben: Ein `watchdog`-Timeout hatte im
  `auto`-Modus bereits das konfigurierte Intervall verbraucht und danach noch
  einmal geschlafen. `pytest -q tests/test_codex_history.py -k
  'watchdog_event_mode or auto_event_mode'` lief mit `3 passed`, die komplette
  Suite mit `132 passed` in `6.52s`. Die Event-Burst-Scanlast ist damit noch
  nicht vollstaendig behoben und bleibt als eigenes Arbeitspaket offen.
- 2026-07-13: Zweiten Collector-Logikfehler behoben: Der Post-Index und der
  Dispatcher liefen nach jedem Watchdog-Event auch bei reinen Duplikat-/Skip-
  Scans. Jetzt laufen sie initial und erneut nur bei echten Importen; der
  Idle-Dispatch bleibt erhalten. Fokussiert `5 passed`, komplett
  `pytest -q tests/test_codex_history.py` mit `133 passed` in `8.41s`.
