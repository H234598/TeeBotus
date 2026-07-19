# Bauplan: Aktueller Plan Healthcheck, TBL-Reconciliation und Statussemantik

**Stand:** 2026-07-13

**Status:** Aktiv, noch nicht abgeschlossen

**Quellstand bei Erstellung:** TeeBotus `1.9.493`

**Aktueller Quellstand:** TeeBotus `1.9.497`; History-Dispatcher `0.2.14`

**Arbeitsbereich:** `/home/teladi/TeeBotus`

## Auftrag

Logikfehler im TeeBotus-Healthcheck, im Cinnamon-Applet und in der
Codex-History-Bridge nachvollziehbar beheben. Der Healthcheck muss echte
Betriebsfehler von erwartbaren Hinweisen unterscheiden, ohne unbekannte oder
widerspruechliche Zustaende zu verschlucken. Die TBL-Reconciliation muss
schreibfrei beweisbar bleiben, bis eine eindeutige Korrekturaktion feststeht.
Die Statussemantik muss ausserdem `accepted`, `delivered` und
`acknowledged` sauber trennen: Eine vom Messenger/API angenommene Nachricht
ist noch keine bestaetigte Zustellung und schon gar keine Lesebestaetigung.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Dieser Bauplan ist eine neue, datierte Arbeitskopie. Aeltere Plaene bleiben als
Historie erhalten, insbesondere:

- `Abgeschlossene Baupläne/Bauplan-Aktueller-Plan-Logikfehler-Healthcheck-Applet-Codex-History-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Healthcheck-Warnungsabbau-und-Codex-History-Reconciliation-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Aktueller-Planstand-Healthcheck-Applet-2026-07-13.md`
- `Abgeschlossene Baupläne/Bauplan-Fortsetzung-Healthcheck-TBL-Reconciliation-2026-07-13.md`

## Leitplanken

- Sicherheit vor Bequemlichkeit: kein automatisches Verknuepfen unbekannter
  Signal-Identitaeten.
- Eine Signal-Verknuepfung darf nur ueber den bestaetigten Account-Linking-Flow
  erfolgen, nicht allein aufgrund eines gemeinsamen Telegram-Nutzers oder
  eines beobachteten Signal-UUIDs.
- Healthchecks, Statusproben und Dry-Runs bleiben schreibfrei.
- Keine Summarys, Outbox-Zeilen oder Dispatch-Resultate loeschen.
- Keine kostenpflichtigen Provider- oder LLM-Aufrufe fuer Diagnose und Tests.
- Secrets, Account-IDs und private Nachrichteninhalte gehoeren nicht in
  Plantexte, Applet-Payloads oder Diagnoseausgaben.
- Die uncommitteten Benutzerdateien `.obsidian/`, `.stfolder/`,
  `Fusion_Packliste.txt`, `Unbenannt.base` und `Unbenannt.canvas` bleiben
  unangetastet.
- Push bleibt ausdruecklich, ein Bot-/Service-Restart erfolgt erst am
  vereinbarten Restart-Fenster oder nach expliziter Freigabe.
- Nach abgeschlossener Implementierung: fokussierte Tests, SemVer-Bump,
  lokaler Commit und Nachweis in diesem Plan.

## Erledigte Arbeit

### Watcher und Collector

- [x] Verschachtelte Sessionroots und direkte JSONL-Roots werden korrekt
  erkannt; fremde JSONL-Dateien ausserhalb des erlaubten Agentenroots werden
  nicht versehentlich importiert.
- [x] Datei-Events werden gefiltert, dedupliziert und waehrend eines kleinen
  Bursts koalesziert.
- [x] Snapshot-Baseline und Eventpfad werden wiederverwendet; ein validiertes
  Event erzwingt keinen zweiten Vollscan.
- [x] Watchdog-Start, Stop und Join raeumen auch bei Exceptions auf.
- [x] Fehlende explizite JSONL-Roots beobachten den vorhandenen Elternordner,
  damit spaetere Dateierzeugung erkannt wird.
- [x] Malformed Watch-, Post-Index- und Dispatch-Reports werden fail-closed
  behandelt und unterdruecken keinen Folgeversuch.
- [x] Idle-Dispatch bleibt aktiv, ohne bei unveraendertem Bestand erneut den
  gesamten Import- und Post-Index-Pfad auszulosen.

### Codex-History-Bridge

- [x] Nur routbare Admin-Empfaenger werden an den Bridge-Dispatcher gegeben.
- [x] Nicht routbare alte Empfaenger werden terminal als
  `recipient_not_routable` markiert; vorhandene Auditdaten bleiben erhalten.
- [x] Mehrere zentrale Queue-Items werden im nicht routbaren Pfad vollstaendig
  als `deferred` gemeldet; ein Limit wird nur angewendet, wenn es positiv ist.
- [x] Nach einem leeren Claim kann der lokale TBL-Spiegel eindeutige zentrale
  terminale Resultate idempotent nachziehen.
- [x] Der lokale Matcher akzeptiert keine widerspruechliche Kombination aus
  gleicher Item-ID und anderem Dedupe-Key; Kollisionen bleiben fail-closed.
- [x] Top-Level- und Payload-Dedupe-Keys eines zentralen Items muessen
  konsistent sein; widerspruechliche Dispatcher-Datensaetze werden verworfen.
- [x] Eine pauschale Requeue- oder Loeschaktion fuer alte lokale Zeilen ist
  weiterhin ausgeschlossen.

### Statussemantik als behobener Bridge-Befund

- [x] `accepted` wird nicht automatisch zu `delivered` hochgestuft.
- [x] `delivered` entsteht nur aus einer echten Zustellbestaetigung oder dem
  ausdruecklich vereinbarten Messenger-Vertrag.
- [x] `acknowledged` beziehungsweise eine Lesebestaetigung bleibt gegenueber
  `delivered` erhalten.
- [x] TeeBotus und der zentrale `History-Dispatcher` verwenden dieselbe
  Aggregations- und Promotionslogik.
- [x] Der lokale Status-Sync verwendet denselben fail-closed ID-/Dedupe-Matcher
  wie die Bridge-Anreicherung; kollidierende Identitaeten koennen keine fremde
  lokale Summary aktualisieren.
- [x] `history.append` akzeptiert keine unbekannten oder leeren Top-Level-
  Statuswerte mehr; fehlerhafte Datensaetze werden vor der Mutation abgewiesen.
- [x] `maintenance.prune` loescht keine History-Items mehr; alte Summarys
  bleiben als verschluesselte Originale erhalten. Nur abgeleitete Audit-,
  Tombstone- und Cursor-Metadaten unterliegen weiter der Aufraeumfrist.

### Healthcheck und Cinnamon-Applet

- [x] Python-Payload und Applet verwenden die strukturierte
  `classification_version=2`-Semantik.
- [x] Actionable Probleme, Warnungen und informative Hinweise werden getrennt
  gezaehlt und angezeigt.
- [x] Deklarative Statuslisten wie `problem_statuses=broken:1` werden mit
  strukturierten Zaehlern abgeglichen.
- [x] Unbekannte oder widerspruechliche Statuswerte werden fail-closed
  behandelt.
- [x] Die Applet-Detailansicht zeigt kurze Ursachen statt nur
  `Health defekt`.
- [x] Eine Aggregate-Zeile mit offenen `queued`-Items wird nicht mehr durch
  erklaerte `no_private_route`-Skips zu einem reinen Hinweis herabgestuft.
  Reine Skip-Aggregate ohne offene Queue bleiben informational.
- [x] Die installierte Applet-Kopie wurde aus dem aktuellen Quellstand
  installiert; Quelle und Installation sind byte-identisch.

## Aktueller Befund

### Signal-Identitaet von Depressionsbot

Der Signal-Runtime-Slot von `Depressionsbot` ist konfiguriert, aber keine
Signal-Identitaet ist sicher mit dem bestehenden Telegram-Account verknuepft.
Die vorhandene Signal-UUID aus einem anderen Account darf nicht automatisch
uebernommen werden. Das ist ein Sicherheits- und Identitaetsproblem, aber noch
kein bestaetigter Defekt des aktiven Accounts.

Die neue Klassifikation lautet daher:

- kein Top-Level-Healthfehler;
- sichtbarer Account-Hinweis `account_identity_notice`;
- naechste Aktion bleibt explizit und sicher: im bereits verknuepften privaten
  Chat `/register` oder `/rotate_secret` verwenden und danach im privaten
  Signal-Chat `/login <account_id> <secret>` senden;
- `/register` in Signal darf nur fuer ein absichtlich getrenntes Konto
  verwendet werden.

### Schreibfreie Live-Probe nach dem Fix

Die direkte Probe mit:

```text
python3 -m TeeBotus.cinnamon_applet status --timeout 30
```

ergab nach dem Queue-Klassifikationsfix:

```text
payload_ok=True
health.status=warning
actionable_problem_count=1
total_problem_count=1
informational_problem_count=21
TeeBotus_Logger queued=166 skipped=101 skip_reasons=no_private_route:101
```

Damit wird die offene lokale TBL-Warteschlange wieder korrekt als actionable
gemeldet. Die 101 begruendeten `no_private_route`-Skips bleiben daneben als
sichtbare Hinweise erhalten. Die Signal-Identity-Notice von `Depressionsbot`
bleibt ebenfalls nicht-actionable.

### Schreibfreie Bridge-Abnahme

Der aktuelle Bridge-Dry-Run fuer `TeeBotus_Logger` wurde ohne Mutation
ausgefuehrt. Er meldete:

```text
would_mirror=162
would_sync=4
reasons=local_outbox_not_in_dispatcher:162,
        dispatcher_terminal_status_delivered:2,
        dispatcher_terminal_status_compacted:2
```

Die konfigurierte TBL-Adminroute ist lokal vorhanden und privat per Telegram
auflosbar. Es wurde trotzdem keine Nachricht gesendet: Das waere eine
unreviewte Alt-Summary-Flut. Die Queue bleibt daher bis zu einer expliziten,
idempotenten Reconciliation oder einem kontrollierten Dispatch bewusst offen.

### Reproduzierter und behobener Statusfehler

Die Vertragsdokumentation in `docs/Codex_Outbox_History_Plan.md` trennt
`sent`, `accepted`, `delivered` und `acknowledged` ausdruecklich. Der aktuelle
Quellstand verletzte diese Trennung an mehreren Stellen:

- `TeeBotus/admin/codex_history.py` wandelt im Reportpfad `accepted` in
  `delivered` um.
- Die TeeBotus-Gesamtstatuslogik liefert bei `accepted + skipped` derzeit
  `delivered` statt `accepted`.
- `/home/teladi/History-Dispatcher/history_dispatcher/store.py` normalisiert
  `accepted` und `acknowledged` beim Persistieren zu `delivered` und kollabiert
  diese Stati erneut in `complete()`.
- Der externe `history.append`-Pfad setzte bei einem Empfaenger ohne Status
  stillschweigend `delivered` und akzeptierte unbekannte Statuswerte.
- Native `read`-/`viewed`-Receipts wurden im Dispatcher zu `acknowledged`
  hochgestuft; Replys und native Receipts waren dadurch nicht mehr getrennt.
- Eine Telegram-API-Annahme war damit faelschlich als Zustellung sichtbar; eine
  Lesebestaetigung kann nicht mehr sauber von einer Zustellung unterschieden
  werden.

Behoben wurde das mit einer monotonen Statusaggregation in beiden Repositories:
`accepted` bleibt `accepted`, `accepted + skipped` bleibt `accepted`, und
Receipts koennen nur auf `delivered` beziehungsweise `acknowledged` anheben.
Der Append-Eingang validiert Empfaengeridentitaet, Duplikate und Status vor
der ersten Datenbankmutation; ein fehlender oder unbekannter Status erzeugt
keinen falschen Zustellnachweis. Native `read`-/`viewed`-Receipts werden nur
als `delivered` gespiegelt; ein aktiver Reply wird explizit als
`acknowledged` gespiegelt.
Auch ein spaeteres `accepted` kann einen bereits gespeicherten
`delivered`-Empfaenger nicht mehr downgraden. TeeBotus steht bei `1.9.496`,
der History-Dispatcher bei `0.2.12`.

### Noch offene Live-Abweichung

Die laufenden Systemd-Prozesse wurden vor den letzten Quellstand-Fixes
gestartet. Die Quellprobe und das installierte Applet sind aktuell, der
laufende Bot-/Collector-Prozess muss jedoch erst in einem erlaubten
Restart-Fenster neu geladen werden. Bis dahin darf nicht behauptet werden,
dass die laufenden Prozesse bereits den neuen Quellstand verwenden. Der
laufende Collector zeigt weiterhin den alten Ressourcenbefund (ca. 2.7 GiB
RSS und ungefaehr eine CPU bei wiederholten 1000er-Scans); der aktuelle
Quellpfad liefert in einer schreibfreien Watchdog-Probe dagegen nur einen
Eventpfad pro Batch.

## Offene Arbeitspakete

### 1. Abschluss des Healthcheck-Fixes

- [x] `runtime_channel_without_identity` von Top-Level-Warnung zu sichtbarem
  Account-Hinweis herabstufen.
- [x] Aggregierte Notice-Zaehler in Pythonstatus und Applet darstellen.
- [x] Regressionen fuer Notice-Parsing und bestehende echte
  `account_identity_warning`-Faelle ergaenzen.
- [x] Regression fuer ein Aggregate mit `queued>0` und erklaerten Skips
  ergaenzen; die offene Queue bleibt actionable.
- [x] SemVer von `1.9.490` auf `1.9.491` bumpen.
- [x] Fokussierte Testausfuehrung nach dem Version-Bump wiederholen.
- [x] Aenderungen lokal committen; der neue Fix und der aktualisierte Bauplan
  sind lokal als Commit `75efd545` festgehalten.
- [x] SemVer von `1.9.492` auf `1.9.493` bumpen und den erweiterten
  ID-/Dedupe-Kollisionsfix mit Regressionen lokal festhalten.

### 2. TBL-Reconciliation schreibfrei abschliessen

- [ ] Lokale TBL-Outbox, lokale Dispatch-Results und zentrale History-Items
  ueber Item-ID und Dedupe-Key klassifizieren.
- [ ] Jede lokale `queued`-Zeile als offen, terminal, historisch oder nicht
  eindeutig einordnen.
- [ ] Jeden `no_private_route`-Skip gegen die zum Skip-Zeitpunkt gueltige
  private Route pruefen.
- [ ] Einen reinen Markdown-/JSON-Report speichern, ohne Mutationen.
- [ ] Erst nach Review einen idempotenten Reconciliation-Befehl fuer eindeutig
  bestaetigte terminale Statuswerte freigeben.

### 2a. Statusvertrag korrigieren

- [x] TeeBotus-Reports geben `accepted` unveraendert weiter.
- [x] Der zentrale Dispatcher persistiert `accepted` und `acknowledged`,
  ohne sie in `delivered` umzuschreiben.
- [x] Delivery- und Read-Receipts stufen den Status nur in der jeweils
  belegten Richtung hoch und setzen ihn niemals zurueck.
- [x] Native `read`-/`viewed`-Receipts bleiben `delivered`; nur aktive Replys
  werden als `acknowledged` gespiegelt.
- [x] Regressionen fuer `accepted`, `accepted + skipped`, `delivered` und
  `acknowledged` in beiden Repositories ergaenzt.
- [x] Beide Repository-Versionen mit SemVer gebumpt und lokal committed;
  Testnachweise stehen unten.

### 3. Collector und Runtime-Live-Abnahme

- [ ] Nach dem naechsten erlaubten Restart CPU, RSS, Scanrate und WAL-
  Schreibvolumen erneut messen.
- [ ] Runtime-Version-Marker, PID, Invocation und Quellversion abgleichen.
- [ ] Applet-Payload und Python-Healthstatus nach dem Restart vergleichen.
- [ ] Bridge-Dispatch mit gemischten routbaren und nicht routbaren Empfaengern
  live pruefen.
- [ ] Mehrere wartende zentrale Queue-Items ohne private Route live pruefen.

## Testnachweis

Bereits erfolgreich, ohne Provider- oder Netzwerkanfragen:

- `pytest -q tests/test_admin_accounts.py tests/test_version_notifications.py`:
  `278 passed`.
- `pytest -q tests/test_cinnamon_applet.py`: `235 passed`.
- `pytest -q tests/test_codex_history.py`: `165 passed`.
- `pytest -q tests/test_codex_history.py tests/test_admin_accounts.py tests/test_version_notifications.py`:
  `444 passed` nach dem Status-Sync-Fix.
- `/home/teladi/History-Dispatcher`: `pytest -q`: `59 passed`.
- Fokussierter Prune-/Statuslauf im History-Dispatcher: `7 passed`.
- Fokussierte Bridge-/Matcher-Regressionen: `4 passed` fuer den aktuellen Fix;
  zuvor `25 passed` fuer den ersten Matcher-Fix.
- Relevante Metadaten-/Kompatibilitaetstests: `97 passed, 51 deselected`.
- Fokussierte Account-Identity-/Health-Tests: `38 passed`.
- `python3 -m compileall -q TeeBotus tests` erfolgreich.
- `git diff --check` erfolgreich.
- `node --check files/teebotus@H234598/applet.js` erfolgreich.
- Installationsparitaet des Applets mit `diff -qr` erfolgreich.
- Statussemantik-Regressionen decken Append, Completion, Receipt-Promotion und
  Empfaenger-Downgrade sowie die Trennung von Native-Receipt und Reply in
  beiden Repositories ab.

## Abnahmekriterien

Der Bauplan ist erst abgeschlossen, wenn:

1. jeder actionable Health-Befund eine reproduzierbare Ursache und eine
   konkrete Aktion besitzt;
2. optionale, noch nicht verknuepfte Signal-Routen sichtbar bleiben, ohne
   einen unbelegten Top-Level-Defekt zu erzeugen;
3. TBL-lokale Queue-/Skip-Zeilen eindeutig klassifiziert sind;
4. keine Summary durch Reconciliation geloescht oder verloren werden kann;
5. der Collector nach Restart unter realistischem Bestand stabil laeuft;
6. Tests, Version, lokaler Commit und Live-Nachweis hier dokumentiert sind;
7. `accepted`, `delivered` und `acknowledged` im gesamten Bridgepfad
   unterscheidbar und durch Tests abgesichert sind.

## Nachweisprotokoll

- 2026-07-13: Neuer Fortsetzungsplan aus dem aktuellen Arbeitsstand erstellt.
- 2026-07-13: Applet-Health nach dem Quellfix schreibfrei geprueft:
  `health.status=ok`, `actionable_problem_count=0`,
  `informational_problem_count=22`, eine sichtbare Signal-Identity-Notice.
- 2026-07-13: Applet installiert und Quell-/Installationsparitaet geprueft;
  SHA-256 beider `applet.js`-Dateien:
  `98c7260152e535835d0ea256e435ac4ddb79b3f41abbe4fa4f54bbf6b1a2842c`.
- 2026-07-13: Nach dem SemVer-Bump auf `1.9.490` liefen die relevanten
  Regressionen mit `426 passed`; der vollstaendige Applet-Lauf lief mit
  `234 passed`. Compileall, JavaScript-Syntax und `git diff --check` waren
  sauber.
- 2026-07-13: Healthcheck-Logikfehler behoben: Aggregate mit
  `queued>0` werden trotz erklaerter `no_private_route`-Skips nicht mehr als
  rein informational eingestuft. Version `1.9.491`; fokussiert `9 passed`,
  relevante Metadaten-/Kompatibilitaetstests `97 passed`, komplette
  Applet-Suite `235 passed`.
- 2026-07-13: Direkte Statusprobe mit aktuellem Quellstand bestaetigte
  `version=1.9.491`, `health.status=warning`,
  `actionable_problem_count=1`, `total_problem_count=1`,
  `informational_problem_count=21` und `qdrant_problem_count=0`. Die
  actionable Zeile ist die offene TBL-Queue; der Prozessmarker fehlt nur beim
  noch nicht neu gestarteten alten Dienstprozess.
- 2026-07-13: Schreibfreier Bridge-Dry-Run fuer TBL klassifizierte 162 lokale
  `would_mirror`-Items und vier terminale `would_sync`-Items. Keine Outbox-,
  Dispatcher- oder Empfaengerdaten wurden veraendert.
- 2026-07-13: Fix lokal als `75efd545` committed; kein Push und kein Restart
  ausgeloest.
- 2026-07-13: ID-/Dedupe-Kollision im Bridge-Matcher reproduziert und
  fail-closed behoben. Eine gleiche Item-ID mit widerspruechlichem Dedupe-Key
  liefert nun keinen Treffer; passende IDs bleiben gueltig. Version `1.9.492`,
  Codex-History-Suite `162 passed`, fokussierte Regressionen `25 passed`.
- 2026-07-13: Zweiten Identitaetsfehler reproduziert: widerspruechliche
  Top-Level-/Payload-Dedupe-Keys werden nun vor Matching und Legacy-Konvertierung
  fail-closed abgewiesen. Version `1.9.493`, Codex-History-Suite `164 passed`,
  aktuelle Regressionen `4 passed`.
- 2026-07-13: Der aktualisierte Bauplan-Nachweis wurde danach separat lokal
  festgehalten; Push und Restart bleiben weiterhin aus.
- 2026-07-13: Laufende Prozesse bewusst noch nicht neu gestartet; die
  20-Commit-Restart-Regel und die fehlende explizite Freigabe bleiben bestehen.
- 2026-07-13: Neuen aktuellen Bauplan aus dem bisherigen Fortsetzungsplan
  erstellt. Der Statusvertrag `accepted` versus `delivered` versus
  `acknowledged` wurde als reproduzierter, noch offener Bridge-Logikfehler
  aufgenommen; TeeBotus steht bei `1.9.493`.
- 2026-07-13: Statusvertrag, Append-Validierung und Receipt-Mapping behoben:
  TeeBotus `1.9.496`, History-Dispatcher `0.2.12`; TeeBotus `443 passed`,
  History-Dispatcher `56 passed`. Push und Restart bleiben aus.
- 2026-07-13: Logikfehler in `maintenance.prune` reproduziert und behoben:
  abgeschlossene History-Items wurden trotz Append-only-Vertrag geloescht.
  Der History-Dispatcher steht jetzt bei `0.2.13`; fokussiert `7 passed`.
- 2026-07-13: Der lokale Bridge-Status-Sync umging den sicheren
  ID-/Dedupe-Matcher und konnte bei einer ID-Kollision die falsche Summary
  aktualisieren. Fail-closed behoben; TeeBotus `1.9.497`, relevante Suite
  `444 passed`, Push und Restart bleiben aus.
- 2026-07-13: `history.append` verschluckte unbekannte Top-Level-Statuswerte
  und legte sie als `queued` an. Fail-closed behoben; der History-Dispatcher
  steht bei `0.2.14`, Vollsuite `59 passed`.
