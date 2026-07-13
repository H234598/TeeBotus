# Bauplan: Fortsetzung Healthcheck, Applet und TBL-Reconciliation

**Stand:** 2026-07-13

**Status:** Aktiv, noch nicht abgeschlossen

**Quellstand bei Erstellung:** TeeBotus `1.9.490`

**Arbeitsbereich:** `/home/teladi/TeeBotus`

## Auftrag

Logikfehler im TeeBotus-Healthcheck, im Cinnamon-Applet und in der
Codex-History-Bridge nachvollziehbar beheben. Der Healthcheck muss echte
Betriebsfehler von erwartbaren Hinweisen unterscheiden, ohne unbekannte oder
widerspruechliche Zustaende zu verschlucken. Die TBL-Reconciliation muss
schreibfrei beweisbar bleiben, bis eine eindeutige Korrekturaktion feststeht.

Der uebergeordnete Arbeitsauftrag lautet:

> Entwickle und finde Logikfehler. Bleibe moeglichst bei einer Datei bzw. einem
> Thema, um Token zu sparen.

Dieser Bauplan ist eine neue, datierte Arbeitskopie. Aeltere Plaene bleiben als
Historie erhalten, insbesondere:

- `Baupläne/Bauplan-Aktueller-Plan-Logikfehler-Healthcheck-Applet-Codex-History-2026-07-13.md`
- `Baupläne/Bauplan-Aktueller-Healthcheck-Warnungsabbau-und-Codex-History-Reconciliation-2026-07-13.md`
- `Baupläne/Bauplan-Aktueller-Planstand-Healthcheck-Applet-2026-07-13.md`

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
- [x] Eine pauschale Requeue- oder Loeschaktion fuer alte lokale Zeilen ist
  weiterhin ausgeschlossen.

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

ergab:

```text
payload_ok=True
health.status=ok
actionable_problem_count=0
total_problem_count=0
informational_problem_count=22
Depressionsbot identity_warnings=0 identity_notices=1
```

Damit ist der vorherige falsche Top-Level-Befund reproduziert und korrigiert:
Der Hinweis bleibt sichtbar, macht aber nicht mehr die gesamte Applet-Health
falsch rot.

### Noch offene Live-Abweichung

Die laufenden Systemd-Prozesse wurden vor den letzten Quellstand-Fixes
gestartet. Die Quellprobe und das installierte Applet sind aktuell, der
laufende Bot-/Collector-Prozess muss jedoch erst in einem erlaubten
Restart-Fenster neu geladen werden. Bis dahin darf nicht behauptet werden,
dass die laufenden Prozesse bereits den neuen Quellstand verwenden.

## Offene Arbeitspakete

### 1. Abschluss des Healthcheck-Fixes

- [x] `runtime_channel_without_identity` von Top-Level-Warnung zu sichtbarem
  Account-Hinweis herabstufen.
- [x] Aggregierte Notice-Zaehler in Pythonstatus und Applet darstellen.
- [x] Regressionen fuer Notice-Parsing und bestehende echte
  `account_identity_warning`-Faelle ergaenzen.
- [x] SemVer von `1.9.489` auf `1.9.490` bumpen.
- [x] Fokussierte Testausfuehrung nach dem Version-Bump wiederholen.
- [x] Aenderungen lokal committen; der Fix und dieser neue Bauplan sind lokal
  als Commit `1e7542f0` festgehalten.

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
- `pytest -q tests/test_cinnamon_applet.py`: `234 passed`.
- Relevante Metadaten-/Kompatibilitaetstests: `97 passed, 51 deselected`.
- Fokussierte Account-Identity-/Health-Tests: `38 passed`.
- `python3 -m compileall -q TeeBotus tests` erfolgreich.
- `git diff --check` erfolgreich.
- `node --check files/teebotus@H234598/applet.js` erfolgreich.
- Installationsparitaet des Applets mit `diff -qr` erfolgreich.

## Abnahmekriterien

Der Bauplan ist erst abgeschlossen, wenn:

1. jeder actionable Health-Befund eine reproduzierbare Ursache und eine
   konkrete Aktion besitzt;
2. optionale, noch nicht verknuepfte Signal-Routen sichtbar bleiben, ohne
   einen unbelegten Top-Level-Defekt zu erzeugen;
3. TBL-lokale Queue-/Skip-Zeilen eindeutig klassifiziert sind;
4. keine Summary durch Reconciliation geloescht oder verloren werden kann;
5. der Collector nach Restart unter realistischem Bestand stabil laeuft;
6. Tests, Version, lokaler Commit und Live-Nachweis hier dokumentiert sind.

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
- 2026-07-13: Direkte Statusprobe mit aktuellem Quellstand bestaetigte
  `version=1.9.490`, `health.status=ok`,
  `actionable_problem_count=0`, `informational_problem_count=22` und
  `qdrant_problem_count=0`. Der Prozessmarker fehlt nur beim noch nicht
  neu gestarteten alten Dienstprozess.
- 2026-07-13: Fix und neuer Bauplan lokal als `1e7542f0` committed; kein Push
  und kein Restart ausgeloest.
- 2026-07-13: Laufende Prozesse bewusst noch nicht neu gestartet; die
  20-Commit-Restart-Regel und die fehlende explizite Freigabe bleiben bestehen.
