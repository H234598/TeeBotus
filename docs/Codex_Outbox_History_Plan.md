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
- CLI Phase 2 teilweise: `python3 -m TeeBotus.admin codex-history append` und `report` funktionieren.
- Phase 4 Dispatcher teilweise: `codex-history dispatch` versendet queued Summaries als Markdown-Anhang an routbare Admin-Accounts, schreibt Dispatch-Results und setzt `dispatching`/`accepted`/`failed`/`skipped` ohne Loeschung.
- Phase 4 Ack-Basis teilweise: `codex-history acknowledge` markiert Summaries append-only als `acknowledged`, setzt `delivery.acknowledged_at` und schreibt ein Dispatch-Result.
- Phase 4 Telegram-Reply-Hook teilweise: Antworten auf ein versendetes Codex-History-Markdown werden ueber `codex_history_dispatch_results.message_ref` erkannt, setzen `delivered_at`/`acknowledged_at` und schreiben append-only Dispatch-Results fuer `delivered` und `acknowledged`.
- Phase 4 Signal-/Matrix-Reply-Hooks teilweise: Signal-Quote-Timestamps und Matrix-`m.in_reply_to.event_id` werden ebenfalls gegen `codex_history_dispatch_results.message_ref` gemappt und bestaetigen passende History-Eintraege append-only.
- Phase 4 Native-Receipt-Basis teilweise: `record_codex_history_delivery_receipt(...)` und `codex-history receipt` markieren passende Dispatches als `delivered`, ohne `acknowledged` zu setzen oder bereits bestaetigte Items zurueckzustufen; Matrix-`ReceiptEvent`s sind an diese API angebunden.
- Phase 3 Watcher teilweise: `codex-history watch --once` importiert Codex-Session-JSONL aus `~/.codex/sessions` oder angegebenen Roots, erkennt `cwd`/Repo, erzeugt redigierte Summaries und dedupliziert ueber `session_id + turn_id + final_message_hash`.
- Phase 3 Watcher teilweise: `codex-history watch` kann bounded pollend laufen oder mit `--follow --event-mode auto` persistent beobachten; `auto` nutzt `watchdog`-Filesystem-Events, wenn das gepinnte `[tools]`-Extra installiert ist, und faellt sonst auf Snapshot/Poll-Warten zurueck.
- Phase 3 systemd teilweise: `teebotus-codex-history-systemd` erzeugt standardmaessig eine persistente User-Unit mit `--follow --event-mode auto` und `Restart=on-failure`; der alte restart-getriebene Bounded-Scan bleibt ueber `--no-follow` verfuegbar.
- Der Watcher bezieht neben `~/.codex/sessions` automatisch vorhandene Agenten-Sessionroots unter `~/.codex-agents/*/.codex/sessions` ein, solange keine expliziten `--sessions-root` Werte gesetzt werden.
- Phase 5 Status/Applet/Report teilweise: Chat-`/status` zeigt `Codex-History` mit `queued`, `failed`, `total` und letztem Repo/Praefix; `--runtime-status` liefert maschinenlesbare `codex_history=<Instanz>`- und `codex_history_repo=<Instanz>`-Zeilen; das Cinnamon-Applet parst diese Zeilen und zeigt Instanz- und Repo-Details im Projekt-Menue; der Admin-CLI-Report liefert pro Repo Status-/Dispatch-Zaehler und letzte Summaries mit Repo-Filter.
- Recovery-/Migrationslisten kennen die neuen JSONL-Fallback-Dateien.
- Der Logger-Bot-Token steht nur noch als Env-Platzhalter im Plan, nicht als tokenfoermiger Klartext.

Offen:

- Native Kanal-Receipts haben eine zentrale API/CLI-Basis; Matrix-Receipts sind angebunden, weitere echte Adapter-Event-Hooks fuer eingehende Plattform-Receipts sind noch offen.
- Signal-/Matrix-Reply-Hooks fuer automatische Messenger-Bestaetigung sind angebunden, aber native Plattform-Receipts bleiben separat offen.
- Native Filesystem-Events sind ueber `watchdog==6.0.0` als gepinnte und gepruefte `[tools]`-Dependency angebunden; ohne installiertes Extra laeuft der Watcher weiter ueber Snapshot/Poll-Fallback.
- Tieferer grafischer Applet-Drilldown, Qdrant/Bibliothekar-Indexierung, grafische Repo-Aufbereitung und strategische Analyse sind noch nicht umgesetzt.

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
- Watcher: ein systemd-User-Service beobachtet Codex-Session-Logs.

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
###  B: Codex-Session-Watcher

Ein systemd-User-Service beobachtet lokale Codex-Session-Dateien und erkennt abgeschlossene Turns/Sessions.

Beispiel:

```ini
[Unit]
Description=TeeBotus Codex history watcher

[Service]
WorkingDirectory=/home/teladi/TeeBotus
EnvironmentFile=-/home/teladi/TeeBotus/.env
ExecStart=/home/teladi/TeeBotus/.venv-py313/bin/python -m TeeBotus.admin codex-history watch --instances-dir /home/teladi/TeeBotus/instances --max-iterations 1 --limit 1000
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Erzeugung:

```bash
python3 -m TeeBotus.codex_history_systemd --repo-root /home/teladi/TeeBotus --print
python3 -m TeeBotus.codex_history_systemd --repo-root /home/teladi/TeeBotus --enable
```

Die systemd-Variante nutzt inzwischen standardmaessig einen persistenten
Watcher mit `--follow --event-mode auto`. Wenn das optionale Python-Paket
`watchdog==6.0.0` aus dem `[tools]`-Extra installiert ist, wartet der Watcher
auf echte Filesystem-Events fuer Codex-Session-JSONL-Dateien; ohne `watchdog`
bleibt er robust und nutzt Snapshot/Poll-Warten. Der alte bounded Scan pro Service-Start ist weiter ueber
`teebotus-codex-history-systemd --no-follow` verfuegbar.

Der Watcher:

- beobachtet `~/.codex/sessions` oder die lokal verwendeten Codex-Logs und integriert auch die Fleet unter `~/.codex-agents/`
- dedupliziert ueber `session_id + turn_id + final_message_hash`
- erkennt `cwd`/Repo aus Session-Metadaten oder Toolcalls
- erzeugt eine kompakte Summary
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

### Phase 3: Watcher

- systemd-User-Service
- beobachtet Codex-Sessionlogs
- erkennt abgeschlossene Sessions
- schreibt Summary in Outbox
- dedupliziert stabil

Stand 2026-06-19:

- `codex-history watch --once` importiert Sessionroots einmalig und dedupliziert ueber Session-/Turn-/Final-Hash.
- `codex-history watch` kann bounded laufen oder mit `--follow` persistent bleiben.
- `--event-mode auto` nutzt optional `watchdog` fuer echte Filesystem-Events und faellt ohne installiertes `[tools]`-Extra auf Snapshot/Poll-Warten zurueck.
- Die systemd-User-Unit nutzt standardmaessig `--follow --event-mode auto`; `--no-follow` erzeugt weiter den alten restart-getriebenen Bounded-Scan.
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
- Offen: weitere echte Adapter-Hooks fuer eingehende native Plattform-Receipts, vor allem falls Signal/Telegram dafuer separat verwertbare Events liefern.

### Phase 5: Applet/Status

- `/status`: Anzahl queued/failed History-Items
- Applet: letzter Codex-History-Eintrag pro Repo
- Admin-CLI: Repo-History-Report

Stand 2026-06-19:

- `/status` zeigt `Codex-History` mit `queued`, `failed`, `total` und letzter Summary.
- `--runtime-status` gibt `codex_history=<Instanz> status=... queued=... failed=... total=... latest_repo=... latest_prefix=...` aus.
- `--runtime-status` gibt zusaetzlich `codex_history_repo=<Instanz> repo=... status=... queued=... failed=... total=... latest_prefix=... latest_status=... latest_title=...` aus.
- Das Cinnamon-Applet parst diese Runtime-Zeilen und zeigt Instanzuebersicht plus Repo-Details im Projekt-Menue.
- `codex-history report` liefert `repo_history` mit pro-Repo Status-/Dispatch-Zaehlern, letzten Summaries und `--repo`/`--summary-limit`.
- Offen: tieferer grafischer Drilldown/Separate Detailansicht im Applet.

### Phase 6: Qdrant + Bibliothek
* Verheirate alles mit Qdrant (64D) und dem Bibliothekar
* Denk dir Kategorien aus, die Qdrant dann benutzen kann und baue sie ein.
* Ein geeignetes, Int8, lokales LLM darf die Kategorien für die Nachricht(en) festlegen.
	* Es ist es klug, das alle paar Stunden als konsolidierten Lauf (niedrigste Prozessprio) laufen zu lassen, statt jede Nachricht einzeln zu kategorisieren.
* User die keine Admins sind dürfen auf keinen Fall etwas von der Sammlung erfahren. 
* Noch weniger (auf gar keinen verdammten Fall) dürfen sie Daten aus den Sammlungen erhalten.
### Phase 7: Grafische Aufbereitung
* baue einen Automatismus, der mit better-git-of-theseus o.ä., in Intervallen, ein hübsches Bild von allen Repos erzeugt und an die Admins schickt.
* Default: 1x am Tag

### Phase 8: Strategische Analyse
* baue einen automatismus der die summaries einem LLM übergiebt, das sich im Kontaxt mit den letzten summaries (hier bieten sich Cache und stateful APIS an) Gedanken über: Zukunft/Verbesserungen, mögliche strategische Ziele, Fallstricke/Logikfehler und mögliche neue Angriffsvektoren/fläche durch die Commits, macht. Das soll dann auch an die Admins ausgegeben werden.
* Default: Aus
* Nach dem Bau: An
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
