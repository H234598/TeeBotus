# Codex -> TeeBotus Outbox/History

Datum: 2026-06-19

## Implementierungsstand

Stand: 2026-06-19

Umgesetzt:

- Phase 1 Datenmodell: `codex_history_outbox`, `codex_history_dispatch_results` und `codex_history_projects` sind als eigene AccountStore-Collections mit JSONL-Fallback angebunden.
- Instanzweiter Speicher nutzt den technischen `INSTANCE_STATE_ACCOUNT_ID`, nicht User-Memory.
- History-Summaries bleiben append-only und starten mit `status=queued`.
- Summary-Nummern laufen pro Repo und verwenden `v<semver> #0001` als Praefix.
- Repo-Metadaten enthalten `repo_id`, Name, Root, Remote, Provider, Branch, Head-Commit und Dirty-Status.
- Vor dem Speichern wird die redigierte Summary erstellt; OpenAI-/Telegram-/generische Secret-Muster werden ersetzt.
- Watcher-Summaries enthalten im Markdown-Header den extrahierten aktiven Goal-Text und den sichtbaren User-Auftrag, wenn diese Informationen in der Codex-Session vorhanden sind.
- Assistant-Zwischenantworten aus `phase=commentary` werden pro Turn als Arbeitsverlauf gespeichert und kurz im Summary-Markdown angezeigt; sie erzeugen bewusst keine eigenen History-Items.
- Run-Summaries werden repo-lokal miteinander verlinkt und enthalten einen kleinen deterministischen Mermaid-Kontextgraphen. `codex-history index` zieht diese Kontextbloecke fuer Altbestand nach.
- CLI Phase 2: `python3 -m TeeBotus.admin codex-history append` und `report` funktionieren.
- Phase 4 Dispatcher: `codex-history dispatch` versendet queued Summaries als Markdown-Anhang an routbare Admin-Accounts, schreibt Dispatch-Results und setzt `dispatching`/`accepted`/`failed`/`skipped` ohne Loeschung.
- Phase 4 Ack-Basis: `codex-history acknowledge` markiert Summaries append-only als `acknowledged`, setzt `delivery.acknowledged_at` und schreibt ein Dispatch-Result.
- Phase 4 Telegram-Reply-Hook: Antworten auf ein versendetes Codex-History-Markdown werden ueber `codex_history_dispatch_results.message_ref` erkannt, setzen `delivered_at`/`acknowledged_at` und schreiben append-only Dispatch-Results fuer `delivered` und `acknowledged`.
- Phase 4 Signal-/Matrix-Reply-Hooks: Signal-Quote-Timestamps und Matrix-`m.in_reply_to.event_id` werden ebenfalls gegen `codex_history_dispatch_results.message_ref` gemappt und bestaetigen passende History-Eintraege append-only.
- Phase 4 Native-Receipts: `record_codex_history_delivery_receipt(...)` und `codex-history receipt` markieren passende Dispatches als `delivered`, ohne `acknowledged` zu setzen oder bereits bestaetigte Items zurueckzustufen; Matrix-`ReceiptEvent`s und Signal-Receipt-Events sind an diese API angebunden.
- Phase 3 Watcher: `codex-history watch --once` importiert Codex-Session-JSONL aus `~/.codex/sessions` oder `~/.codex-agents/*/sessions` oder angegebenen Roots, erkennt `cwd`/Repo, erzeugt redigierte Summaries und dedupliziert ueber `session_id + turn_id + final_message_hash`.
- Phase 3 Watcher: `codex-history watch` kann bounded pollend laufen oder mit `--follow --event-mode auto` persistent beobachten; `auto` nutzt `watchdog`-Filesystem-Events, wenn das gepinnte `[tools]`-Extra installiert ist, und faellt sonst auf Snapshot/Poll-Warten zurueck.
- Phase 3 systemd: `teebotus-codex-history-collector` erzeugt standardmaessig die systemweite root-Unit `teebotus-codex-history-collector.service` mit `--follow --event-mode auto` und `Restart=on-failure`; der alte restart-getriebene Bounded-Scan bleibt ueber `--no-follow` verfuegbar.
- Der Collector uebergibt bei einem Repo unter `/home/teladi/...` explizit `/home/teladi/.codex/sessions` und `/home/teladi/.codex-agents`, damit `User=root` nicht versehentlich nur `/root/.codex/sessions` beobachtet. Der Watcher selbst nutzt ohne explizite Roots weiter `~/.codex/sessions` und vorhandene `~/.codex-agents/*/sessions`.
- Phase 5 Status/Applet/Report: Chat-`/status` zeigt `Codex-History` mit `queued`, `failed`, `total` und letztem Repo/Praefix; `--runtime-status` liefert maschinenlesbare `codex_history=<Instanz>`- und `codex_history_repo=<Instanz>`-Zeilen inklusive Artefakt-Typmix; das Cinnamon-Applet parst diese Zeilen, zeigt Instanz-/Repo-Details im Projekt-Menue und bietet pro Repo einen Codex-History-Drilldown; der Admin-CLI-Report liefert pro Repo Status-/Dispatch-Zaehler und letzte Summaries mit Repo-Filter.
- Phase 6/7/8: admin-only Bibliothekar-/Qdrant-Export, lokale Kategorisierung, Mermaid-Graph, SVG-Artefakte und queuebarer strategischer Analysebericht sind angebunden.
- Recovery-/Migrationslisten kennen die neuen JSONL-Fallback-Dateien.
- Der Logger-Bot-Token steht nur noch als Env-Platzhalter im Plan, nicht als tokenfoermiger Klartext.

Bewusst optional / Einschraenkungen:

- Native Kanal-Receipts haben eine zentrale API/CLI-Basis; Matrix-Receipts und Signal-Read/Delivery-Receipt-Events sind angebunden. Telegram-Bot-API liefert fuer Bot-Nachrichten keine echten Delivery-/Read-Receipts, daher gibt es dort bewusst keinen nativen Hook.
- Native Filesystem-Events sind ueber `watchdog==6.0.0` als gepinnte und gepruefte `[tools]`-Dependency angebunden; ohne installiertes Extra laeuft der Watcher bewusst ueber Snapshot/Poll-Fallback.
- Optional hochwertigeres Graph-Rendering ist als `mmdc`/`auto`-Pfad angebunden; weitere Layout-Qualitaet bleibt optional.

## Kurzantwort

Ja, das koennen wir so bauen.

Der richtige Ansatz ist nicht, Codex per Prompt daran zu erinnern, sondern ein lokaler, automatischer History-Collector:

1. Codex laeuft wie bisher.
2. Ein lokaler Watcher oder Wrapper erkennt abgeschlossene Codex-Laeufe.
3. Der Watcher erzeugt eine kurze, indexierbare Summary.
4. Diese Summary wird append-only in eine TeeBotus-History-Outbox geschrieben.
5. Der Dispatcher verschickt sie an die autorisierten Status-/Admin-Empfaenger.
6. Die Summary bleibt dauerhaft erhalten und bekommt nur Statusfelder wie `queued`, `sent`, `accepted`, `delivered`, `acknowledged`, `failed`.

Wichtig: Fuer Projektgeschichte sollten wir die bestehende `Status_Outbox` nicht ueberladen, sondern ein eigenes, aber gleich aufgebautes Modul bauen: `Projects_and_Coding_History_and_Outbox` .

## Warum nicht nur "Codex soll das immer tun"?

Eine reine Anweisung an Codex ist zu schwach:

- Sie greift nur, wenn die aktive Instanz die Regel im Kontext hat.
- Sie kann bei Context-Compaction, neuen Sessions oder Fremdinstanzen verloren gehen.
- Sie garantiert nicht, dass wirklich jeder Lauf protokolliert wird.
- Sie kann versehentlich sensible Details in eine Summary schreiben, wenn kein zentraler Filter davor sitzt.

Automatisch wird es, wenn ausserhalb des Prompt-Kontexts geloggt wird:

- Wrapper: `codex` wird ueber ein lokales Startskript aufgerufen.
- Collector: ein systemweiter root-systemd-Service beobachtet Codex-Session-Logs.

Watcher als Hauptweg, Wrapper als Zusatz fuer bessere Metadaten.

## Gewuenschtes Datenmodell

Eine History-Zeile sollte nicht nur Text sein, sondern ein strukturiertes, indexierbares Dokument.

Beispiel:

```json
{
  "id": "hist_...",
  "schema_version": 1,
  "kind": "codex_run_summary",
  "source": "codex_session_watcher",
  "status": "queued",
  "created_at": "2026-06-19T12:00:00+00:00",
  "updated_at": "2026-06-19T12:00:00+00:00",

  "project": {
    "repo_id": "sha256:...",
    "repo_name": "TeeBotus",
    "repo_root": "/home/teladi/TeeBotus",
    "remote_url": "git@github.com:.../TeeBotus.git",
    "provider": "github",
    "branch": "main",
    "head_commit": "c185b71...",
    "dirty": false
  },

  "version": {
    "semver": "1.8.0",
    "tag": "v1.8.0",
    "summary_number": 42,
    "summary_prefix": "v1.8.0 #0042"
  },

  "codex": {
    "session_id": "...",
    "agent_instance_id": "...",
    "cwd": "/home/teladi/TeeBotus",
    "started_at": "...",
    "finished_at": "..."
  },

  "summary": {
    "title": "Status-Auth-Summaries in durable Outbox gefuehrt",
    "markdown": "v1.8.0 #0042 ...",
    "bullets": [
      "Status-Auth-Summaries werden vor dem Versand queued.",
      "Dispatch-Ergebnisse markieren sent/failed/skipped.",
      "Admin-CLI status-auth report ergaenzt."
    ],
    "changed_files": [
      "TeeBotus/runtime/admin_accounts.py",
      "TeeBotus/admin/status_auth_admin.py"
    ],
    "tests": [
      "tests/test_runtime_admin_accounts.py: 15 passed"
    ]
  },

  "delivery": {
    "target_group": "status_admins",
    "attempts": 0,
    "last_attempt_at": "",
    "sent_at": "",
    "accepted_at": "",
    "delivered_at": "",
    "acknowledged_at": ""
  },

  "indexing": {
    "indexable": true,
    "repo_history": true,
    "keywords": ["codex", "outbox", "status-auth", "history"]
  },

  "status_history": [
    {
      "at": "2026-06-19T12:00:00+00:00",
      "status": "queued",
      "reason": "codex_run_finished"
    }
  ]
}
```

## Repo-Feld und mehrere Projekte

Ja, ein Repo-Feld ist sinnvoll und noetig.

Die History sollte repo-uebergreifend funktionieren. Dafuer brauchen wir einen stabilen `repo_id`.

Empfohlene Bildung:

1. Wenn Git-Remote vorhanden ist: normalisierte Remote-URL hashen.
2. Wenn kein Remote vorhanden ist: `repo_root` hashen.
3. Wenn kein Git-Repo vorhanden ist: Arbeitsverzeichnis + Projektname hashen.

Damit koennen mehrere Repos in derselben SQL-Collection liegen:

- `/home/teladi/TeeBotus`
- `/home/teladi/speed-of-cinnamon`
- `/home/teladi/.local/share/wirtelprimpf/github/Katzenbilder`
- spaeter beliebig weitere lokale Projekte

Die Abfrage wird dann:

- alle History-Eintraege
- nur ein Repo
- nur ein Zeitraum
- nur ein SemVer-Tag
- nur fehlgeschlagene Laeufe
- nur Commits/Releases/Features/Bugfixes

## Wo speichern?

Nicht in User-Memory.

Das ist Projekt-/Runtime-History, keine private Nutzererinnerung.

Baue (in):

- SQL primaer
- JSONL nur als Fallback/Recovery
- eigene Collection: `codex_history_outbox`
- eigene Collection: `codex_history_dispatch_results`
- eigene Collection: `codex_history_projects`

Technisch koennen wir das in TeeBotus ueber denselben AccountStore-Mechanismus abbilden wie die Status-Outbox. Fuer instanzweite Daten bietet sich der bestehende technische Instance-State-Account an, nicht ein echter Useraccount.

## Statusmodell: nicht loeschen

Summaries sollen generell nicht mehr geloescht werden.

Stattdessen:

- `queued`: erzeugt, noch nicht verschickt
- `dispatching`: ein Worker hat den Eintrag gerade geclaimt
- `sent`: an den Messenger/API-Sender uebergeben
- `accepted`: Transport/API hat den Versand akzeptiert
- `delivered`: echte Zustellung bestaetigt, falls der Kanal das hergibt
- `acknowledged`: Zielperson/Empfaenger hat aktiv bestaetigt oder der Bot hat eine Antwort darauf erhalten
- `failed`: Versand fehlgeschlagen
- `skipped`: bewusst nicht gesendet
- `superseded`: spaeterer Eintrag ersetzt die Benachrichtigung, aber der alte bleibt historisch erhalten

Wichtig: `sent` und `delivered` sind nicht dasselbe.

Bei Telegram bedeutet eine erfolgreiche `sendMessage`-Antwort praktisch: Telegram hat die Nachricht angenommen. Das ist nicht automatisch ein Lesebeleg. Bei Signal/Matrix haengt es ebenfalls vom Backend und den verfuegbaren Receipts ab. Deshalb sollten wir sauber trennen:

- `sent_at`: TeeBotus hat den Sender aufgerufen.
- `accepted_at`: Messenger/API hat keinen Fehler zurueckgegeben.
- `delivered_at`: echter Delivery-Receipt, falls vorhanden.
- `acknowledged_at`: User/Admin hat reagiert oder bestaetigt.

## Wie Codex automatisch loggt

### A: Codex-Wrapper

Wir legen ein lokales Skript vor den echten Codex-Binary in den PATH, z.B.:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
session_hint="$(date +%s)-$$"

export TEEBOTUS_CODEX_HISTORY_ENABLED=1
export TEEBOTUS_CODEX_HISTORY_REPO_ROOT="$repo_root"
export TEEBOTUS_CODEX_HISTORY_SESSION_HINT="$session_hint"

/path/to/real/codex "$@"
status=$?

python3 -m TeeBotus.admin.codex_history append \
  --repo-root "$repo_root" \
  --session-hint "$session_hint" \
  --exit-code "$status"

exit "$status"
```

Vorteile:

- Einfach.
- Gute Repo-Metadaten.
- Funktioniert fuer alle Codex-Starts, die ueber diesen Wrapper laufen.

Nachteile:

- Verpasst bereits laufende Instanzen.
- Verpasst Starts, die den echten Binary direkt aufrufen.
- Muss sehr vorsichtig mit Exit-Codes und TTY umgehen.

Dabei dürfen die Agenten unter /home/teladi/.codex-agents/{a1, b1, c1, ...} nicht vergessen werden!.
###  B: Codex-Session-Collector

Ein systemweiter systemd-Service beobachtet lokale Codex-Session-Dateien und erkennt abgeschlossene Turns/Sessions. Die Unit laeuft explizit als `User=root`, damit alle lokalen Sessionroots lesbar sind; die Default-Roots bleiben trotzdem auf den TeeBotus-Repo-Owner `/home/teladi` verdrahtet.

Beispiel:

```ini
[Unit]
Description=TeeBotus Codex history collector

[Service]
Type=simple
User=root
WorkingDirectory=/home/teladi/TeeBotus
EnvironmentFile=-/home/teladi/TeeBotus/.env
ExecStart=/home/teladi/TeeBotus/.venv-py313/bin/python -m TeeBotus.admin codex-history watch --instances-dir /home/teladi/TeeBotus/instances --event-mode auto --poll-interval 300 --limit 1000 --follow --sessions-root /home/teladi/.codex/sessions --sessions-root /home/teladi/.codex-agents --post-index --dispatch --dispatch-limit 0
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Erzeugung:

```bash
teebotus-codex-history-collector --repo-root /home/teladi/TeeBotus --print
sudo env PYTHONPATH=/home/teladi/TeeBotus /home/teladi/TeeBotus/.venv-py313/bin/python -m TeeBotus.codex_history_systemd --repo-root /home/teladi/TeeBotus --enable
```

Der Enable-Aufruf nutzt absichtlich den Repo-/venv-Python-`-m`-Pfad. Ein
user-lokaler Entry-Point aus `/home/teladi/.local/bin` kann unter `sudo`
sonst roots Python-Umgebung sehen und das editable User-Paket nicht importieren.

Die systemd-Variante nutzt inzwischen standardmaessig einen persistenten
Watcher mit `--follow --event-mode auto`. Wenn das optionale Python-Paket
`watchdog==6.0.0` aus dem `[tools]`-Extra installiert ist, wartet der Watcher
auf echte Filesystem-Events fuer Codex-Session-JSONL-Dateien; ohne `watchdog`
bleibt er robust und nutzt Snapshot/Poll-Warten. Der alte bounded Scan pro Service-Start ist weiter ueber
`teebotus-codex-history-collector --no-follow` verfuegbar. Der alte Entry-Point
`teebotus-codex-history-systemd` bleibt als Kompatibilitaetsalias erhalten,
war aber nie der Service-Name.

Der Watcher:

- beobachtet `/home/teladi/.codex/sessions` und rekursiv `/home/teladi/.codex-agents`, wenn der root-Collector aus dem TeeBotus-Repo gerendert wird
- ueberspringt bei root-/Directory-Scans sehr grosse, gerade noch aktive Sessionlogs kurzzeitig, damit der Timer nicht an der live wachsenden Codex-Session haengen bleibt; explizite Einzeldatei-Imports bleiben weiterhin moeglich
- liest grosse abgeschlossene Sessionlogs ueber Kopf-/Tail-Fenster, damit Session-Metadaten und finale Antwort ohne mehrere hundert MB RAM-/I/O-Last importierbar bleiben
- dedupliziert ueber `session_id + turn_id + final_message_hash`
- erkennt `cwd`/Repo aus Session-Metadaten oder Toolcalls
- erzeugt eine kompakte Summary
- speichert `Goal`, `Auftrag`, `Bearbeiteter Auftrag` und eine kurze Zwischenantworten-Timeline, wenn die Codex-Session diese Daten liefert
- verlinkt Summaries repo-lokal mit vorherigem/naechstem Eintrag und haengt einen kleinen Mermaid-Kontext an
- schreibt append-only in `codex_history_outbox`

Vorteile:

- Jede Codexinstanz kann automatisch erfasst werden.
- Keine aktive Anweisung an Codex noetig.
- Besser fuer Fremd-/Parallel-Instanzen.
- Kann nachtraeglich alte Sessions importieren.

Nachteile:

- Parser muss robust gegen Formatwechsel sein.
- Dedupe ist Pflicht.
- Secrets muessen zentral gefiltert werden.

### Dann -->C: Hybrid

Das ist aus meiner Sicht die beste Loesung.

- Wrapper setzt Metadaten und startet Codex normal.
- Watcher liest die echten Sessionlogs.
- CLI kann manuell nachtragen/reparieren/importieren.

Damit bekommen wir automatische Erfassung plus robuste Nachverarbeitung.

## Besseres Muster als "nach jedem Lauf freitextloggen"

Der Collector sollte nicht einfach die finale Antwort blind speichern.

Besser:

1. Rohdaten sammeln:
   - Session-ID
   - CWD
   - Git-Repo
   - Changed files
   - Commits
   - Testbefehle und Ergebnisse
   - finale Assistenzantwort

2. Lokal redigieren:
   - API-Keys entfernen
   - Tokens entfernen
   - lange Logs kuerzen
   - personenbezogene Chatinhalte nicht ungefiltert uebernehmen

3. Summary erzeugen:
   - semantisch kurz
   - nummeriert
   - mit SemVer/Tag-Prefix
   - repo- und commitbezogen

4. In SQL schreiben:
   - append-only
   - `status=queued`
   - `indexable=true`

5. Dispatch separat:
   - Versand an Status/Admin-Accounts
   - Ergebnis in Dispatch-Results
   - Outbox-Zeile bleibt erhalten

## Nummerierung

Nummerierung sollte pro Repo laufen, nicht global.

Beispiel:

- `TeeBotus`: `v1.8.0 #0001`, `v1.8.0 #0002`
- `speed-of-cinnamon`: `v0.2.1 #0001`
- `Katzenbilder`: `v0.4.0 #0001`

Wenn kein SemVer gefunden wird:

- `untagged #0001`
- oder `0.0.0-dev #0001`

Bei TeeBotus koennen wir `TeeBotus.__version__` nutzen. Fuer andere Repos:

- Git-Tag, wenn vorhanden
- `pyproject.toml`
- `package.json`
- `Cargo.toml`
- `VERSION`
- fallback: `untagged`

## Indexierung

Ja, diese Summaries duerfen und sollten indexiert werden.

Index-Felder:

- repo name
- repo root
- remote URL
- branch
- commit hash
- tag/version
- changed files
- summary bullets
- tests
- feature/bugfix/chore Kategorie
- Status: queued/sent/failed

Wichtig: Indexiert wird die redigierte Summary, nicht die komplette rohe Codex-Session.

## Sicherheitsregeln

Der Collector muss vor dem Schreiben redigieren:

- `sk-...`
- Gemini/API-Keys
- Telegram Bot Tokens
- Signal Secrets
- Account Secrets
- Session Tokens
- Cookies
- private Chattexte, wenn sie nicht projektbezogen sind

Ausserdem:

- Raw transcripts nicht dauerhaft in der History-Outbox speichern.
- Optional Raw-Referenz nur als lokaler Pfad/Hash.
- Summaries duerfen indexiert werden.
- Secrets nie.

## Konkreter Bauplan

### Phase 1: Datenmodell

- `Codex_History_Outbox.jsonl` als Fallback-Dateiname
- SQL-Collection `codex_history_outbox`
- `Codex_History_Dispatch_Results.jsonl`
- SQL-Collection `codex_history_dispatch_results`
- Store-Methoden:
  - `read_codex_history_outbox`
  - `write_codex_history_outbox`
  - `append_codex_history_item`
  - `read_codex_history_dispatch_results`
  - `append_codex_history_dispatch_result`

### Phase 2: CLI

Neue CLI:

```bash
python3 -m TeeBotus.admin codex-history append --repo-root /home/teladi/TeeBotus
python3 -m TeeBotus.admin codex-history report --repo TeeBotus --format json
python3 -m TeeBotus.admin codex-history dispatch
python3 -m TeeBotus.admin codex-history watch
```

### Phase 3: Watcher / Collector

- systemweiter `teebotus-codex-history-collector.service` mit `User=root`
- beobachtet Codex-Sessionlogs
- erkennt abgeschlossene Sessions
- schreibt Summary in Outbox
- dedupliziert stabil

Stand 2026-06-19:

- `codex-history watch --once` importiert Sessionroots einmalig und dedupliziert ueber Session-/Turn-/Final-Hash.
- `codex-history watch` kann bounded laufen oder mit `--follow` persistent bleiben.
- `--event-mode auto` nutzt optional `watchdog` fuer echte Filesystem-Events und faellt ohne installiertes `[tools]`-Extra auf Snapshot/Poll-Warten zurueck.
- Die systemweite Collector-Unit nutzt standardmaessig `--follow --event-mode auto`; `--no-follow` erzeugt weiter den alten restart-getriebenen Bounded-Scan.
- `watchdog==6.0.0` ist als optionale Tool-Abhaengigkeit gepinnt, im Adapter-Lock enthalten und wird durch Adapter-/Plan2-Checks geprueft.

### Phase 4: Dispatcher

- verschickt neue History-Summaries an Status/Admin-Gruppe
- markiert `sent/accepted/failed`
- loescht nie
- schreibt Dispatch-Results

Stand 2026-06-19:

- `codex-history dispatch` markiert Transportannahme als `accepted` und schreibt Dispatch-Results.
- `codex-history acknowledge --item-id ...` kann aktive Bestaetigung manuell/administrativ setzen, ohne die Summary zu loeschen.
- `codex-history receipt --channel ... --chat-id ... --message-ref ...` kann echte Plattform-Receipts oder importierte Receipt-Ereignisse als `delivered` nachtragen.
- Telegram-Replys auf ein versendetes History-Dokument markieren die Summary als `delivered` und direkt danach als `acknowledged`; dabei werden `reply_message_ref` und eine redigierte `reply_text_preview` auditierbar in den Dispatch-Results gespeichert.
- Signal-Replys mit Quote-Timestamp und Matrix-Replys mit `m.in_reply_to.event_id` nutzen dieselbe kanalneutrale Ack-Logik.
- Native Receipt-Basis setzt nur `delivered` und stuft bereits `acknowledged` Items nicht zurueck.
- Matrix-`ReceiptEvent`s werden gegen `codex_history_dispatch_results.message_ref` gemappt und setzen passende History-Eintraege auf `delivered`.
- Native Receipts: Matrix-`ReceiptEvent`s und Signal-Receipt-Events werden gegen `codex_history_dispatch_results.message_ref` gemappt. Telegram bleibt bewusst ohne nativen Receipt-Hook, weil die Bot API keine echten Delivery-/Read-Receipts fuer Bot-Nachrichten liefert.

### Phase 5: Applet/Status

- `/status`: Anzahl queued/failed History-Items
- Applet: letzter Codex-History-Eintrag pro Repo
- Admin-CLI: Repo-History-Report

Stand 2026-06-19:

- `/status` zeigt `Codex-History` mit `queued`, `failed`, `total` und letzter Summary.
- `--runtime-status` gibt `codex_history=<Instanz> status=... queued=... failed=... total=... latest_repo=... latest_prefix=... latest_kind=... run_summaries=... strategies=... graphs=... other=...` aus.
- `--runtime-status` gibt zusaetzlich `codex_history_repo=<Instanz> repo=... status=... queued=... failed=... total=... run_summaries=... strategies=... graphs=... other=... latest_prefix=... latest_status=... latest_kind=... latest_title=...` aus.
- Das Cinnamon-Applet parst diese Runtime-Zeilen, zeigt Instanzuebersicht plus Repo-Details im Projekt-Menue und haengt einen Codex-History-Drilldown mit Status, Queue, Typmix und letztem Eintrag pro Repo an.
- `codex-history report` liefert `repo_history` mit pro-Repo Status-/Dispatch-Zaehlern, letzten Summaries und `--repo`/`--summary-limit`.
- `codex-history bibliothekar-export` schreibt redigierte Projekthistory-Markdowns in `data/Codex_History_Bibliothek`, absichtlich getrennt von der normalen Nutzerbibliothek `data/Bibliothek`.
- `codex-history index` fuehrt Export und optionalen Qdrant-Rebuild in einem Admin-Lauf zusammen.
- `codex-history index` aktualisiert vor dem Export die Summary-Kontextbloecke fuer Altbestand: repo-lokale Vorher/Nachher-Links und eingebetteten Mermaid-Kontext.
- `codex-history watch --post-index` aktualisiert den admin-only Bibliothekar-Export nach Watcher-Scans; `--post-index-qdrant` haengt optional den separaten Qdrant-Rebuild an.
- `teebotus-codex-history-collector` rendert standardmaessig `--post-index`, kann den Export mit `--no-post-index` abschalten und Qdrant explizit mit `--post-index-qdrant` aktivieren.
- `teebotus-codex-history-collector --collector-timer` rendert einen leichten Oneshot pro Minute mit `--limit 10`, `--post-index`, `--dispatch` und `--dispatch-limit 0` (`0` = alle wartenden Outbox-Eintraege); groessere Backfills laufen weiter explizit ueber `--limit ...` oder den persistenten Follow-Collector.
- `teebotus-codex-history-collector --index-timer` rendert/installiert zusaetzlich einen low-priority Oneshot-Service plus Timer fuer `codex-history index --qdrant --qdrant-ensure`; Default-Rhythmus: `24h`.
- `codex-history categorize` annotiert Codex-History-Eintraege optional mit einem lokalen, remote-geblockten LLM-Profil; `codex-history index --categorize` kann diesen Schritt vor Export/Qdrant ausfuehren.
- `codex-history graph-export` schreibt eine admin-only Mermaid-Projekthistory nach `data/Codex_History_Bibliothek/graphs`; `codex-history index --graph` kann sie im selben Batch erzeugen.
- `codex-history graph-export --svg` schreibt zusaetzlich ein dependency-freies SVG-Bild; `--svg-engine auto|mmdc` kann optional Mermaid CLI (`mmdc`) nutzen. `codex-history index --graph --graph-svg --graph-svg-engine ...` erzeugt es im selben Low-Priority-Batch.
- `codex-history graph-export --queue-svg` queued das SVG als `kind=codex_graph_artifact` mit `image/svg+xml` Attachment fuer den bestehenden Admin-Dispatcher.
- `codex-history strategic-analysis` erzeugt aus den letzten Codex-History-Summaries einen admin-only Strategie-/Risiko-Bericht als queuebares Outbox-Markdown; `codex-history index --strategic-analysis` kann den Bericht vor Export/Qdrant erzeugen.
- Strategische Analysen nutzen einen Quellen-Fingerprint als Cache: gleicher Repo-Filter, gleiches Profil und unveraenderte Summaries erzeugen keinen neuen LLM-Lauf; `--force` bzw. `--strategic-analysis-force` erzwingt einen neuen Bericht.
- `teebotus-codex-history-collector --index-timer --index-dispatch` fuegt dem Low-Priority-Index-Service ein `ExecStartPost` fuer `codex-history dispatch` hinzu.
- Das Cinnamon-Applet bietet Terminal-Aktionen fuer Codex-History-Report, manuellen Indexlauf, manuelle Strategieanalyse und explizite Timer-Aktivierung mit Graph/SVG/Strategie/Dispatch.
- Der Export vergibt deterministische Kategorien wie `codex-history`, `project-history`, `repo-*`, `status-*`, `change-feature`, `change-bugfix`, `change-test`, `change-docs`, `change-security`, `change-dependency`, `change-runtime`, `change-memory`, `change-bibliothekar` und `change-llm`, damit ein separater Qdrant-/Bibliothekar-Index sie als Filter/Tags nutzen kann.
- Erledigt: tieferer Applet-Drilldown als Repo-Untermenues im Projekt-Menue; separate grosse Detailansicht bleibt optional, falls das Applet spaeter mehr Platz bekommt.

### Phase 6: Qdrant + Bibliothek
* Erledigt: `codex-history bibliothekar-export` erzeugt admin-only Markdown-Dokumente aus `codex_history_outbox`.
	* Zielordner: `instances/<Instanz>/data/Codex_History_Bibliothek`
	* Der normale Runtime-Bibliothekar liest weiterhin nur `data/Bibliothek`; dadurch leakt Codex-History nicht an normale Nutzer.
	* Die Dokumente enthalten Metadaten, Status, Version, Repo, Commit, Delivery-Felder, Summary und Kategorien.
* Erledigt: separater Qdrant-Index fuer diese admin-only Quelle.
	* Collection: `teebotus_codex_history_chunks`
	* `teebotus-embedding codex-history-rebuild` erzeugt Qdrant-Chunks direkt aus `codex_history_outbox`.
	* `teebotus-embedding collections-ensure --include-codex-history` legt die optionale Collection an/prueft sie.
	* Der Index nutzt dieselbe Qdrant-Bibliothekar-Payloadform, aber eine andere Collection als normale Nutzerbibliothek und Usermemory.
* Erledigt: Automatischer Rebuild/Export nach Watcher-Scans.
	* `codex-history watch --post-index` aktualisiert die admin-only Markdown-Quelle nach jedem Scan, auch im persistenten `--follow`-Modus.
	* `codex-history watch --post-index-qdrant` aktualisiert optional auch die separate Qdrant-Collection nach jedem Scan.
	* `teebotus-codex-history-collector` setzt `--post-index` standardmaessig, Qdrant bewusst nur explizit.
* Erledigt: separater Timer/Low-Priority-Batch fuer Qdrant-Rebuild.
	* `teebotus-codex-history-collector --index-timer` erzeugt `teebotus-codex-history-index.service` und `teebotus-codex-history-index.timer`.
	* Der Service ist `Type=oneshot` und laeuft mit `Nice=10`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=7`, `CPUWeight=10`, `IOWeight=10`.
		* Default-Timer: `OnUnitActiveSec=24h`, `RandomizedDelaySec=15min`, `Persistent=true`.
* Erledigt: lokale LLM-Kategorisierung im Low-Priority-Batch.
	* `codex-history categorize --profile local_ollama` nutzt nur lokale LLM-Profile; Remote-Profile wie OpenAI/Gemini/Groq/HF-Pool werden fuer diesen Pfad abgelehnt.
	* `codex-history index --categorize --categorize-profile local_ollama` kategorisiert vor Markdown-Export und optionalem Qdrant-Rebuild.
	* `teebotus-codex-history-collector --index-timer --index-categorize` haengt die Kategorisierung an den low-priority Timer-Service.
	* LLM-Ausgaben werden gegen eine feste Kategorie-Whitelist normalisiert; Repo-, Status- und Admin-Scope-Tags bleiben deterministisch, damit kein Modell falsche Scope-Tags erzeugt.
* Kategorien fuer Qdrant sind eingebaut. Ohne `--categorize` bleiben sie deterministisch/statisch; mit `--categorize` werden zusaetzliche lokale LLM-Tags persistiert.
* Ein geeignetes, Int8, lokales LLM darf die Kategorien fuer die Nachricht(en) festlegen.
	* Es ist klug, das alle paar Stunden als konsolidierten Lauf (niedrigste Prozessprio) laufen zu lassen, statt jede Nachricht einzeln zu kategorisieren.
* User die keine Admins sind dürfen auf keinen Fall etwas von der Sammlung erfahren. 
* Noch weniger (auf gar keinen verdammten Fall) dürfen sie Daten aus den Sammlungen erhalten.
### Phase 7: Grafische Aufbereitung
* Erledigt: `codex-history graph-export` erzeugt ein admin-only Mermaid-Markdown mit Repo -> Summary -> Status/Kategorie-Kanten.
	* Ziel: `instances/<Instanz>/data/Codex_History_Bibliothek/graphs/codex_history_graph.md`
	* `codex-history index --graph` erzeugt den Graph im kombinierten Low-Priority-Indexlauf.
	* `teebotus-codex-history-collector --index-timer --index-graph` haengt den Graph-Export an den Timer.
* Erledigt: Jede Run-Summary kann zusaetzlich einen kleinen eingebetteten Mermaid-Kontext enthalten.
	* Der eingebettete Kontext bleibt repo-lokal, damit repo-gefilterte Exporte keine fremden Projekttitel leaken.
	* Der groessere projektuebergreifende Graph bleibt der separate admin-only Graph-Export.
* Erledigt: `--svg`/`--graph-svg` erzeugt zusaetzlich ein SVG-Bild im selben Ordner.
	* Default: `--svg-engine builtin`, dependency-frei.
	* Optional: `--svg-engine auto` nutzt Mermaid CLI `mmdc`, wenn lokal installiert, und faellt sonst mit Report-Warnung auf builtin zurueck.
	* Explizit: `--svg-engine mmdc` verlangt Mermaid CLI und scheitert sauber, wenn sie fehlt oder fehlschlaegt.
* Erledigt: `--queue-svg`/`--graph-queue-svg` legt das SVG als queuebares Admin-Outbox-Attachment ab; der bestehende `codex-history dispatch` versendet es mit Dispatch-Results/Acks.
* Erledigt: `teebotus-codex-history-collector --index-timer --index-dispatch` kann den Versand nach dem Index per `ExecStartPost` automatisch ausloesen.
* Optional: hochwertigeres Rendering ueber Mermaid CLI `mmdc` ist angebunden; weitere Renderer wie better-git-of-theseus bleiben optional.
* Default: 1x am Tag (`OnUnitActiveSec=24h`).

### Phase 8: Strategische Analyse
* Erledigt: `codex-history strategic-analysis` uebergibt die letzten Codex-History-Summaries an ein LLM und erzeugt einen Markdown-Bericht mit:
	* Zukunft/Verbesserungen
	* strategischen Zielen
	* Fallstricken/Logikfehlern
	* neuen Angriffsoberflaechen
	* Empfehlungen
* Der Bericht wird als `kind=codex_strategy_analysis` in `codex_history_outbox` queued und ist damit ueber den bestehenden Admin-Dispatcher als Markdown-Datei versendbar.
* `codex-history index --strategic-analysis` erzeugt den Bericht vor Export/Qdrant, damit er im selben Batch in Bibliothekar/Qdrant landen kann.
* `teebotus-codex-history-collector --index-timer --index-strategic-analysis` haengt die Analyse an den Low-Priority-Index-Timer.
* Default im Timer: Aus. Remote-Profile sind nur mit `--strategic-analysis-allow-remote` bzw. `--index-strategic-analysis-allow-remote` erlaubt.
* Erledigt: periodischer Admin-Versand ist im systemd-Index-Timer per `--index-dispatch` opt-in.
* Erledigt: Live-Aktivierung nach expliziter Freigabe ist im Cinnamon-Applet als Terminal-Aktion angebunden; sie installiert/aktiviert den Index-Timer mit Graph-SVG, Queue-SVG, strategischer Analyse und Dispatch.
* Erledigt: State-/Cache-Optimierung fuer strategische Analysen; Quellen-Fingerprint, Profil und Repo-Filter verhindern doppelte LLM-Laeufe bei unveraenderten Quellen. `--force` und `--index-strategic-analysis-force` umgehen den Cache bewusst.
## Ungenauer Ablauf:

1. Eigene `codex_history_outbox`, nicht die Status-Outbox weiter aufblasen.
2. Eigener Telegrambot/Token für den Nachrichtenoutput (Telegramname: "TeeBotus - Logger"): `<TEEBOTUS_LOGGER_TELEGRAM_TOKEN>`
3. Repo-ID als Pflichtfeld.
4. Summary-Nummerierung pro Repo.
5. Watcher als automatische Hauptloesung.
6. Wrapper nur als Zusatz fuer bessere Metadaten.
7. Keine Loeschung mehr, nur Statusuebergaenge.
8. `delivered` nur setzen, wenn der Messenger wirklich einen Receipt liefert oder wenn ein Reply auf die konkrete versendete Summary beobachtet wurde; sonst nur `accepted`.
9. Ab an Qdrant und den Bibliothekar.
10. Mach was hübsches drauß
11. Monitoring/Analyse und CD

Damit bekommen wir eine echte, repo-uebergreifende Projekthistory, die auch spaeter durchsuchbar und vom Bibliothekar/Memory-System indexierbar ist.
