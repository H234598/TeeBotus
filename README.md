# TeeBotus

TeeBotus ist ein kleiner Python-Bot mit additiven Runtime-Slots fuer Telegram, Signal und Matrix sowie optionalen Extras fuer lokale Transkription, LLM-Provider, RAG/Bibliothekar und Agenten-Workflows. Er kann mehrere Instanzen mit getrennten Einstellungen starten.

## Funktionen

- `/start` begruesst neue Nutzer
- `/help` zeigt die verfuegbaren Befehle
- `/ping` antwortet mit `pong`
- `/status` zeigt Laufstatus, TeeBotus-Version, GitHub-Commithistorie, Memory-Groesse und Userfile-Verschluesselung des anfragenden Nutzers
- `/history` zeigt GitHub-Repo, Commits und lokale Release-Tags. Fragen wie `Was ist neu?`, `Programmhistorie`, `Welche Commits gab es?`, `Release Log`, `Changelog` oder `Programmänderungen` nutzen denselben Offline-Pfad.
- `/chatid` zeigt die aktuelle Chat-ID
- `/reset` loescht den Text-LLM-Kontext fuer den aktuellen Chat
- `/reset_memorys` fragt nach und loescht danach nur die eigenen User-Memory-Eintraege
- frei formulierte Bitten wie `loesch meine Erinnerungen` nutzen denselben bestaetigten User-Memory-Reset
- `/Call_a_Teladi` fragt nach einer Emergency Message und leitet die naechste Telegram-Nachricht an Teladi weiter
- `/cleanup N` loescht die letzten N seit Bot-Start gemerkten Nachrichten aus dem aktuellen Chat
- `/cleanup all` loescht alle zuletzt gemerkten Nachrichten aus dem aktuellen Chat
- `/codex Prompt` startet lokal `codex exec` aus dem Bot-Prozess heraus
- `/voice Text` erzeugt eine Telegram-Sprachnachricht
- `/voicemodel <stimme>` speichert die bevorzugte OpenAI-Stimme fuer eigene Sprachnachrichten; OpenAI-Voices: https://platform.openai.com/docs/guides/text-to-speech#voice-options
- `/mimic_voice on|off|before|after` nutzt ein laufend verbessertes Sprechweisen-Profil aus eigenen Sprachnachrichten fuer TTS
- eingehende Telegram-Sprachnachrichten werden transkribiert und wie Textnachrichten verarbeitet
- normale Textnachrichten werden per aktiver Instanz-`Bot_Verhalten.md` beantwortet oder als Echo zurueckgegeben
- optionaler OpenAI-Fallback fuer freie Fragen
- pro Telegram-Token wird der echte Botname per `getMe` geladen

## Bot einrichten

1. In Telegram `@BotFather` oeffnen.
2. `/newbot` senden und den Anweisungen folgen.
3. Den Token in eine lokale `.env` kopieren:

```bash
cd TeeBotus
cp .env.example .env
```

4. `.env` bearbeiten und die instanzspezifischen Tokens ersetzen.
5. Fuer OpenAI-Antworten den passenden instanzspezifischen OpenAI-Key setzen.

## Starten

Standard ohne Zusatzargument ist die Einzelinstanz `Bote_der_Wahrheit`:

```bash
cd TeeBotus
set -a
source .env
set +a
python3 -m TeeBotus
```

Eine bestimmte Einzelinstanz startest du so:

```bash
TELEGRAM_BOT_INSTANCE=Depressionsbot python3 -m TeeBotus
```

Alle konfigurierten Instanzen startest du so:

```bash
python3 -m TeeBotus --all
```

Ohne `TELEGRAM_BOT_INSTANCES` erkennt der All-Start alle Ordner unter `instances/`, die eine `Bot_Verhalten.md` enthalten. Mit `TELEGRAM_BOT_INSTANCES` kannst du die Liste explizit begrenzen:

```bash
TELEGRAM_BOT_INSTANCES=Bote_der_Wahrheit,Depressionsbot python3 -m TeeBotus --all
```

`TELEGRAM_BOT_INSTANCES=all` beziehungsweise `TEEBOTUS_INSTANCES=all` schaltet wieder auf automatische Ordner-Erkennung, statt eine Instanz namens `all` zu starten. `all`/`auto` darf dabei nicht mit konkreten Instanznamen gemischt werden; leere Felder wie `Depressionsbot,,Bote_der_Wahrheit` sind Konfigurationsfehler.

Alternativ geht der All-Start auch per Environment:

```bash
TELEGRAM_BOT_INSTANCE=all python3 -m TeeBotus
```

Fuer parallel laufende Bots braucht jede Telegram-Bot-Identitaet einen eigenen BotFather-Token.

Der Bot laeuft dann im Terminal. Mit `Ctrl+C` beendest du ihn.

Der Bot loggt nach `stdout`, wenn Telegram-Nachrichten eingehen oder Bot-Nachrichten ausgehen. Geloggt werden nur Metadaten wie Chat-ID, Message-ID, Nachrichtentyp und Laenge, nicht der Nachrichteninhalt.

`ALL_BOTS_DEFAULT.md` enthaelt unter `## Laufzeitkonfiguration` echte Default-Schalter fuer den Start. Werte aus Shell, systemd, Docker oder `.env` haben Vorrang; die Default-Datei fuellt nur fehlende Environment-Werte.

## Account-Runtime

`TeeBotus/bot.py` bleibt der stabile Entry-Point. Telegram, Signal und Matrix werden ueber dieselbe Runtime-Konfiguration als gleichwertige Slots gestartet. Der vorhandene Telegram-Long-Poller bleibt nur der konkrete Telegram-Transport; der Bot-Kern haengt nicht mehr am Poller als Sonderfall.

Die Runtime-Konfiguration kannst du separat pruefen:

```bash
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix
```

Mit `--notify-admins` filtert der Runtime-Status Warnungen und Fehler aus
der Diagnoseausgabe und schickt sie als Markdown-Datei an die konfigurierte
Admin-Account-Gruppe der Logger-Instanz `TeeBotus_Logger`. Die geprueften
Problemzeilen koennen aus allen ausgewaehlten Instanzen stammen; ausgegeben
und in `Status_Outbox` protokolliert werden Runtime-Status-Summaries aber nur
ueber TBL. Die Gruppe ist account-basiert, nicht transport-basiert; verschickt
wird ueber die gespeicherte private Route des jeweiligen TBL-Admin-Accounts:

```bash
python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix --notify-admins
```

`--channels telegram` startet nur Telegram-Slots. `--channels signal` startet nur konfigurierte Signal-Slots. `--channels matrix` startet nur konfigurierte Matrix-Slots. Kombinationen mit Telegram starten Signal und Matrix im Hintergrund und danach den Telegram-Runtime-Slot mit Long-Polling-Transport. Channel-Listen duerfen keine leeren Felder enthalten; `telegram,,signal` ist ein Konfigurationsfehler.

## Cinnamon-Applet

Das Repo enthaelt ein lokales Cinnamon-Panel-Applet unter
`files/teebotus@H234598`. Es orientiert sich an der Applet-Struktur von
Speed of Cinnamon: `metadata.json`, `settings-schema.json`, `applet.js`,
`stylesheet.css` und ein eigenes Icon liegen direkt im Applet-Ordner.

Das Hauptmenue ist als Operator-Oberflaeche gedacht:

- Status & Diagnose: Runtime-Status aktualisieren, Status JSON kopieren,
  Runtime-Status im Terminal oeffnen und Applet-Einstellungen oeffnen.
- Runtime Details, Messenger, LLM & Dienste, Memory & Speicher: gruppierte
  Auszuege aus `python3 -m TeeBotus --runtime-status`.
- Bibliothekar: Status, Bibliotheksordner und Bibliothekar-Hilfe.
- Proaktiv: manuellen Proaktiv-Lauf, Timerstatus und Logs.
- Bot-Steuerung: `systemctl --user start|restart|stop <Unit>` mit optionaler
  `zenity`-Rueckfrage.
- Schnellbefehle: haeufige Chat-Kommandos wie `/status`, `/info`, `/help`,
  `/voicemodel`, `/mimic_voice`, `/register`, `/memory_reset` in die
  Zwischenablage kopieren.
- Projekt: Repo-Ordner, GitHub und Commits oeffnen.

Die Einstellungen steuern Repo-Pfad, Python-Binary, Runtime-Channels,
systemd-Unit, Refreshintervall, Panel-Label, sichtbare Menuesektionen,
Terminalprogramm, Bibliothekar-/Proaktiv-Instanz und Projektlinks. Die Applet-
Statusabfrage laeuft ueber den festen Helfer:

```bash
python3 -m TeeBotus.cinnamon_applet status --repo-root "$PWD" --channels telegram,signal --unit teebotus.service
```

Zum lokalen Testen installiert der Helfer den Applet-Ordner nach
`~/.local/share/cinnamon/applets/teebotus@H234598`; danach kann er in den
Cinnamon-Applet-Einstellungen aktiviert werden:

```bash
python3 scripts/install_cinnamon_applet.py
```

Der Hauptbot kann ebenfalls als User-systemd-Service reproduzierbar erzeugt werden. Der Renderer startet keine Bot-Loops im Print-Modus und erzeugt eine gehaertete Unit mit `NoNewPrivileges=true`, `PrivateTmp=true`, `.env` als optionalem EnvironmentFile und `python -m TeeBotus --all --channels telegram,signal,matrix`:

```bash
teebotus-systemd --repo-root "$PWD" --print
teebotus-systemd --repo-root "$PWD" --enable
```

Der Proactive-Agent-Scheduler laeuft separat vom Botstart. Ein periodischer User-systemd-Timer kann reproduzierbar erzeugt werden. Ohne `--interval` prueft der Timer alle 5 Minuten:

```bash
teebotus-proactive-systemd --repo-root "$PWD" --instance Depressionsbot --print
teebotus-proactive-systemd --repo-root "$PWD" --instance Depressionsbot --enable
```

Der erzeugte Timer ruft standardmaessig `teebotus-proactive --dispatch --plan --tool-plan` auf. Das fuehrt lokale Reflection-Planung, Due-Selection und Versand ueber die konfigurierten Proactive-Backends aus. LLM-Planung ist mit `--llm-plan` verfuegbar; die native Tool-Agent-Planung mit lokal validierten Memory-/Outbox-Toolcalls ist mit `--tool-plan` im systemd-Renderer der Default. Toolcalls laufen zusaetzlich durch `ProactiveToolCallDecision`, damit bekannte Tools nur mit Pflichtargumenten und erlaubten Argumenten in die Plananwendung kommen. Beide Pfade bleiben hinter `TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES` beziehungsweise Instanz-Flag und passender Rollen-LLM-Konfiguration aktiv.

Der Codex-History-Collector ist eine eigene systemweite systemd-Unit. Der neue
primaere Renderer heisst `teebotus-codex-history-collector` und erzeugt
standardmaessig `teebotus-codex-history-collector.service` mit `User=root`,
damit Sessiondaten unter `/home/teladi/.codex/sessions` und
`/home/teladi/.codex-agents` auch dann gelesen werden, wenn mehrere
Codex-Homes beteiligt sind. Der alte Entry-Point
`teebotus-codex-history-systemd` bleibt nur als Kompatibilitaetsalias erhalten;
er war nie der Service-Name selbst.

```bash
teebotus-codex-history-collector --repo-root "$PWD" --print
sudo env PYTHONPATH="$PWD" "$PWD/.venv-py313/bin/python" -m TeeBotus.codex_history_systemd --repo-root "$PWD" --enable
```

Die Unit startet `codex-history watch --follow --event-mode auto
--poll-interval 300 --limit 1000 --post-index`, nutzt die lokale `.env` als
optionales EnvironmentFile und installiert nach `/etc/systemd/system`. Fuer den
alten User-Unit-Modus gibt es explizit `--user-unit`; der Default ist bewusst
der root-Collector. Der Enable-Aufruf nutzt bewusst den Modulpfad mit
`PYTHONPATH`, weil ein user-lokal installierter Entry-Point unter `sudo` sonst
aus roots Python-Umgebung importiert.

Fuer nicht-user-getriggerte Proactive-Aufrufe sind drei Rollen vorgesehen: `PROACTIVE_PLAN`, `PROACTIVE_DECISION` und `PROACTIVE_WORKER`. OpenAI bleibt ueber `OPENAI_API_KEY_<INSTANCE>_PROACTIVE_PLAN`, `OPENAI_API_KEY_<INSTANCE>_PROACTIVE_DECISION` und `OPENAI_API_KEY_<INSTANCE>_PROACTIVE_WORKER` kompatibel; die jeweiligen `_SERVICES`-Varianten werden ebenfalls akzeptiert. Providerneutrale Rollen-LLMs werden ueber dieselben Runtime-LLM-Settings wie normale Kanaele konfiguriert, z.B. `TEEBOTUS_LLM_PROFILE_<INSTANCE>_PROACTIVE_PLAN=gemini_flash_stateful`, `TEEBOTUS_LLM_API_KEY_<INSTANCE>_PROACTIVE_PLAN=...`, analog fuer `PROACTIVE_DECISION` und `PROACTIVE_WORKER`. Fuer Gemini-Keyrotation sind zusaetzlich rollenspezifische Ringe/Buckets moeglich, z.B. `TEEBOTUS_GEMINI_API_KEY_RING_<INSTANCE>_PROACTIVE_WORKER` oder `TEEBOTUS_GEMINI_API_KEYS_<INSTANCE>_PROACTIVE_WORKER_ACCOUNT_1`. Ohne explizite rollenbezogene LLM-Settings nutzt jede Rolle die Kette: Rollen-Key, `OPENAI_API_KEY_<INSTANCE>_PROACTIVE` oder `_PROACTIVE_SERVICES`, `OPENAI_API_KEY_PROACTIVE` oder `_PROACTIVE_SERVICES`, `OPENAI_API_KEY_<INSTANCE>_BACKGROUND` oder `_BACKGROUND_SERVICES`, danach `OPENAI_API_KEY_BACKGROUND` oder `_BACKGROUND_SERVICES`. Die alte sichtbare Instanzform wie `Depressionsbot_BACKGROUND_SERVICES` bleibt kompatibel. Normale instanzweite oder globale Userantwort-Keys (`OPENAI_API_KEY_<INSTANCE>`, `OPENAI_API_KEY`) werden fuer `proactive`/`background` weiterhin nicht als Fallback genutzt; Telegram-/Signal-/Matrix-Userantworten bleiben davon getrennt.

Alte Memory-Rettungsartefakte werden nicht geloescht. `scripts/maintain_instance_quarantine.py` verschiebt nur bekannte Altpfade wie `.pre-*`, `*.unreadable-*`, alte `Account_*_Quarantine`-Ordner, `accounts.pre-*`-Snapshots und Pseudo-Instanzen ohne `Bot_Verhalten.md` in eine zentrale datierte Quarantaene unter `instances/.quarantine/cleanup-<timestamp>` und schreibt dort ein `manifest.json`. Aktive Stores bleiben ausgeschlossen: `data/accounts/accounts`, `Account_Memory.sqlite3`, `Account_Memory.backup.sqlite3` und WAL/SHM-Dateien unter dem aktiven `data/accounts` werden nicht bewegt.

```bash
python3 scripts/maintain_instance_quarantine.py quarantine --instances-dir instances
python3 scripts/maintain_instance_quarantine.py quarantine --instances-dir instances --apply
python3 scripts/maintain_instance_quarantine.py install-systemd --instances-dir instances --enable
```

Der installierte User-systemd-Timer startet taeglich nur den Retention-Pfad. Er archiviert rohe `cleanup-*`-Bundles erst nach sieben Tagen oder nachdem eine SQL-Backup-Bestaetigung geschrieben wurde; danach kann er die rohe Bundle-Kopie entfernen, das `.tar.gz`-Archiv bleibt erhalten. Die Bestaetigung wird lokal so gesetzt:

```bash
python3 scripts/maintain_instance_quarantine.py confirm-sql-backup --instances-dir instances --backup-label "postgresql daily backup" --apply
```

Usergewuenschte Erinnerungen laufen ebenfalls ueber die Proactive-Outbox. Klassische Formulierungen werden lokal erkannt; bei optionaler strukturierter `ReminderDecision` kann `recurrence` als `daily`, `weekly`, `monthly` oder `every N minutes/hours/days/weeks` gespeichert werden. Nach erfolgreichem Versand wird ein wiederkehrendes Reminder-Item mit naechstem `due_at` erneut gequeued.

Signal braucht das Python-Paket `signalbot`, die native `signal-cli-rest-api` und `signal-cli`. Die festen Versionen stehen in `adapter-dependencies.lock`; die komplette gepinnte Adapter-Schicht kann reproduzierbar installiert und danach geprueft werden mit:

```bash
python3 scripts/install_adapter_deps.py
python3 scripts/check_adapter_deps.py
```

`nio-bot 1.0.2.post1` deklariert upstream noch `matrix-nio==0.20.*`. TeeBotus prueft aktuell den echten Runtime-Override `matrix-nio==0.25.2` mit `h11==0.16.0`, weil unsere genutzten `nio-bot`-/`matrix-nio`-Vertraege damit laufen und die moderne `httpcore`-/`httpx`-Kette importierbar bleibt. Upstream-Metadatenkonflikte werden durch die getrennte, sequenzierte Installation in `requirements.txt` und `scripts/install_adapter_deps.py` abgefangen; der eigentliche Vertrag wird durch `scripts/check_adapter_deps.py` validiert.

Der Dependency-Doctor meldet zusaetzlich `python runtime choice=...`. Python 3.14 bleibt damit pruefbar, wird aber als `advisory` markiert, solange dort OpenAI mit der 3.14-kompatiblen Vorgabelogik gefahren wird. Fuer eine saubere LLM-/Tool-Resolver-Schiene ist Python 3.13 aktuell die empfohlene TeeBotus-Runtime.

Empfohlene lokale 3.13-Runtime ohne Aenderung des Systemdefaults:

```bash
sudo dnf install -y python3.13 python3.13-devel
python3 scripts/setup_python313_runtime.py --install-systemd --enable-systemd --channels telegram,signal
```

Wenn `.venv-py313/bin/python` existiert, verwendet `python3 -m TeeBotus.systemd` diese Runtime automatisch vor `.venv/bin/python` und `python3`, solange kein explizites `--python` gesetzt ist. Der Helper-Aufruf schreibt und aktiviert die User-Unit explizit mit dieser Runtime.

Pro Instanz muessen Service-URL und Telefonnummer zusammen gesetzt sein:

```bash
SIGNAL_BOT_SERVICE_DEPRESSIONSBOT=http://127.0.0.1:8080
SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT=+49...
```

Die Erreichbarkeit des externen Signal-Dienstes pruefst du ohne Botstart:

```bash
python3 -m TeeBotus --runtime-status --channels signal
```

Wenn ein lokaler konfigurierter Signal-Dienst nicht erreichbar ist, startet TeeBotus `signal-cli-rest-api` automatisch mit `MODE=json-rpc`, `PORT=<port>` und der lokalen `signal-cli`-Config und prueft danach erneut. Fuer nicht-lokale Services bleibt ein nicht erreichbares Backend ein harter Startfehler. `signalbot` nutzt dabei `InMemoryConfig`; persistenter Bot-Zustand liegt in TeeBotus, Signal-Account-Daten liegen bei `signal-cli`.

`--runtime-status --channels signal` meldet zusaetzlich den Signal-Account-Zustand:

```text
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=registered
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=missing
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=unavailable
```

`missing` bedeutet: das Backend ist erreichbar, aber `signal-cli-rest-api` listet die konfigurierte Telefonnummer nicht in `/v1/accounts`. Dann muss der native Signal-Account zuerst in `signal-cli` eingerichtet werden. Als Primaergeraet:

```bash
signal-cli -a +49... register
signal-cli -a +49... verify <sms-code>
signal-cli listAccounts
```

Als verlinktes Zweitgeraet:

```bash
signal-cli link -n TeeBotus
signal-cli listAccounts
```

Erst wenn `signal-cli listAccounts` die konfigurierte Nummer kennt, startet `python3 -m TeeBotus --all --channels telegram,signal` dauerhaft ohne Signal-Preflight-Fehler.

Mehrere Signal-Slots werden positionsgleich konfiguriert:

```bash
SIGNAL_BOT_SERVICES_DEPRESSIONSBOT=http://127.0.0.1:8080,http://127.0.0.1:8081
SIGNAL_BOT_PHONE_NUMBERS_DEPRESSIONSBOT=+49...,+49...
```

Alternativ koennen weitere Slots nummeriert gesetzt werden:

```bash
SIGNAL_BOT_SERVICE_DEPRESSIONSBOT_2=http://127.0.0.1:8081
SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT_2=+49...
```

In Signal erzeugt `/register` einen neuen TeeBotus-Account fuer diesen Signal-Weg. Um einen bestehenden Telegram-Account zu verbinden, zuerst im privaten Telegram-Chat `/register` oder `/rotate_secret` nutzen und danach im privaten Signal-Chat senden:

```text
/login <account_id> <secret>
```

Matrix nutzt `nio-bot` als Backend und braucht einen Matrix-User mit Access-Token. Pro Instanz muessen Homeserver, User-ID und Access-Token zusammen gesetzt sein:

```bash
MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT=https://matrix.example.org
MATRIX_BOT_USER_ID_DEPRESSIONSBOT=@teebotus:example.org
MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT=syt_...
MATRIX_BOT_DEVICE_ID_DEPRESSIONSBOT=TEEBOTUS
```

Mehrere Matrix-Slots werden positionsgleich konfiguriert:

```bash
MATRIX_BOT_HOMESERVERS_DEPRESSIONSBOT=https://matrix-a.example,https://matrix-b.example
MATRIX_BOT_USER_IDS_DEPRESSIONSBOT=@bot-a:example,@bot-b:example
MATRIX_BOT_ACCESS_TOKENS_DEPRESSIONSBOT=syt_a,syt_b
MATRIX_BOT_DEVICE_IDS_DEPRESSIONSBOT=DEV_A,DEV_B
```

Alternativ koennen weitere Slots nummeriert gesetzt werden:

```bash
MATRIX_BOT_HOMESERVER_DEPRESSIONSBOT_2=https://matrix-b.example
MATRIX_BOT_USER_ID_DEPRESSIONSBOT_2=@bot-b:example
MATRIX_BOT_ACCESS_TOKEN_DEPRESSIONSBOT_2=syt_b
MATRIX_BOT_DEVICE_ID_DEPRESSIONSBOT_2=DEV_B
```

`MATRIX_BOT_DEVICE_ID_*` ist optional pro Slot. Ein nummerierter Device-ID-Wert darf fruehere Slots leer lassen, muss aber zu einem existierenden Homeserver/User/Token-Slot gehoeren.

Die Erreichbarkeit der konfigurierten Matrix-Homeserver pruefst du ohne Botstart:

```bash
python3 -m TeeBotus --runtime-status --channels matrix
```

Wenn ein konfigurierter Matrix-Homeserver nicht erreichbar ist, bricht ein Matrix-Start vor dem Adapterstart mit einer klaren Fehlermeldung ab.

Zum Verbinden eines bestehenden TeeBotus-Accounts im Matrix-Privatraum:

```text
/login <account_id> <secret>
```

Der neue Account-Layer speichert Kommunikationswege wie `telegram:user:<id>`, `signal:uuid:<id>` oder `matrix:user:<id>` als Identities eines instanzinternen Accounts. Account-Secrets werden nicht im Klartext gespeichert, sondern als HMAC-SHA512-Verifier mit instanzgebundenem Secret-Service-Pepper.
Normales `/login <account_id> <secret>` bleibt instanzgebunden. Runtime-Admins duerfen denselben Login-Befehl auch mit Account-ID und Secret einer anderen lokalen Instanz nutzen; der Bot prueft das Secret gegen die Quellinstanz und legt erst danach einen lokalen externen Account-Link an.

Strukturierter Account-Memory kann auf SQLite oder PostgreSQL umgestellt werden. Auf diesem Host ist SQLite der gemessene lokale Primary-Backend; PostgreSQL bleibt optional und muss per DSN erreichbar sein:

```bash
export TEEBOTUS_ACCOUNT_MEMORY_BACKEND=sqlite
python3 scripts/migrate_account_memory_to_database.py --backend sqlite --instances-dir instances --dry-run
python3 scripts/migrate_account_memory_to_database.py --backend sqlite --instances-dir instances --delete-json-files
python3 scripts/sync_account_memory_sqlite_backup.py --accounts-root instances/Depressionsbot/data/accounts

export TEEBOTUS_ACCOUNT_MEMORY_BACKEND=postgres
export TEEBOTUS_ACCOUNT_MEMORY_POSTGRES_DSN='postgresql://USER:PASSWORD@HOST:5432/DBNAME'
python3 scripts/migrate_account_memory_to_database.py --backend postgres --instances-dir instances --dry-run
python3 scripts/migrate_account_memory_to_database.py --backend postgres --instances-dir instances --delete-json-files
```

SQLite und PostgreSQL speichern Memory-Payloads weiterhin AES-256-GCM-verschluesselt pro Eintrag. Querybar bleiben nur Metadaten wie `id`, `kind`, `memory_type`, `importance`, `salience`, `access_count` und Keywords. Der PostgreSQL-Treiber ist als `psycopg[binary]==3.3.4` gepinnt. Wenn `TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH` gesetzt ist, nutzt der Bot eine sekundäre SQLite-DB als Fallback und loggt periodische Critical-Warnungen, bis der Primary-Backend wieder funktioniert.

Benchmark:

```bash
PYTHONPATH=. python3 scripts/benchmark_memory_store.py --backend jsonl --entries 1000 --select-runs 20
PYTHONPATH=. python3 scripts/benchmark_memory_store.py --backend sqlite --entries 1000 --select-runs 20
PYTHONPATH=. python3 scripts/benchmark_memory_store.py --backend postgres --entries 1000 --select-runs 20
PYTHONPATH=. python3 scripts/benchmark_memory_store.py --backend postgres --postgres-dsn 'postgresql://USER:PASSWORD@HOST:5432/DBNAME' --require-postgres
```

Der uebergreifende Quick-Benchmark fuer Plan2-Kernpfade schreibt Markdown und JSON standardmaessig in den Obsidian-Incoming-Ordner und verschickt den Markdown-Bericht an die Admin-Accounts. Die Messungen selbst nutzen keine echten Provider-Calls und keine API-Kosten; der Admin-Versand ist mit `--no-admin-notify` abschaltbar:

```bash
python3 scripts/run_benchmarks.py --quick
```

Abgedeckt werden Account-Memory, Bibliothekar lokal plus Haystack/Qdrant-Backendpfad mit Fake-DocumentStore, die lokale Retrieval-Matrix fuer e5-small/e5-base/bge-m3, Reranker und Local/LlamaIndex/Haystack, SourceHarvester-Quality-Gates inklusive `harvest -> promote -> index` ohne Blind-Ingest, LLM-Router, synthetische LLM-Nachrichtenpfad-Latenzen fuer OpenAI-Responses/Gemini-Interactions/LiteLLM/hf_pool ohne Provider-Calls, die LLM-Pfadmatrix aus Engine/Decision-Layer/Bibliothekar/Keyword-Memory/Fake-Qdrant, hf_pool-Health plus providerfreie hf_pool-Eval-Matrix, Proactive-Agent, Messenger-Adapter-Contracts, YouTube-/Transkriptionsparser, Status/Doctor, Datenbank-Fallback-Policy und LangGraph-Flows. PostgreSQL wird im Quick-Modus als `skipped` markiert, solange kein expliziter DSN uebergeben wird. Fuer Regressionen kann ein frueherer JSON-Lauf als Baseline verglichen werden:

```bash
python3 scripts/run_benchmarks.py --quick --baseline-json /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-latest.json --output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-compare.md --json-output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-compare.json
```

Live-Benchmarks bleiben opt-in und erzeugen getrennte `live_*`-Ergebnisse:

```bash
python3 scripts/run_benchmarks.py --live-hf --live-qdrant --profile hf_pool_default --output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-live.md --json-output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-live.json
```

Echte LLM-Provider/API-Latenzen sind ein Notfall-Benchmark und nie Teil der Standard- oder normalen Live-Laeufe. Er braucht bewusst zwei Schalter: CLI-Flag plus exakten Env-Bestaetigungswert. Fallbacks sind in diesem Benchmark zur Kostenkontrolle deaktiviert, und `--emergency-live-llm-max-calls` begrenzt die Gesamtzahl echter LLM-Calls:

```bash
TEEBOTUS_EMERGENCY_LIVE_LLM_BENCHMARK=NOTFALL_KOSTEN_AKZEPTIERT \
python3 scripts/run_benchmarks.py --emergency-live-llm --emergency-live-llm-max-calls 3 \
  --output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-live-llm.md \
  --json-output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-benchmarks-live-llm.json
```

`hf_pool_eval_matrix` laeuft dagegen immer lokal und kostenfrei. Es prueft die
Plan3-Zwecke `structured_decision`, `normal_chat`, `psychology_explainer`,
`bibliothekar_answer` und `summarizer`, dazu JSON-Validitaet,
Psychologie-Rubrik, Quellen-/Chunk-Faithfulness, Summary-Faithfulness,
Provider-Failure-Fallback und Cooldown-Fallback ohne Netzaufruf.
Der Retrieval-Benchmark vergleicht die Usermemory-Modelle
`intfloat/multilingual-e5-small` und `intfloat/multilingual-e5-base`, die
Buchmodelle `BAAI/bge-m3` und `intfloat/multilingual-e5-base`, Local/
LlamaIndex/Haystack-Backends sowie `BAAI/bge-reranker-v2-m3` gegen den
unge-rerankten `BAAI/bge-m3`-Top-Kandidatenlauf. In Standardlaeufen ist der
Reranker ein lokales Fake-/Keyword-Backend, kein Remote-Call.

Plan2-Akzeptanztests:

```bash
python3 scripts/check_plan2_acceptance.py
```

Der Runner startet keine Bot-Loops und ruft bewusst nicht `python3 -m TeeBotus --all` auf. Er prueft Version, Runtime-Status, die Plan2-Testgruppen, Bibliothekar-Fixtures, Quick-Benchmarks und Adapter-Abhaengigkeiten. Legacy-Import-Unit-Tests laufen nicht im Standardpfad; sie sind nur mit `--include-legacy-import-tests` explizit aktiv. Zum reinen Anzeigen der Kommandos:

```bash
python3 scripts/check_plan2_acceptance.py --list
python3 scripts/check_plan2_acceptance.py --dry-run
```

Fuer CI ohne native Signal-Binaries kann `--adapter-deps-python-only` genutzt
werden. Damit laufen die Python-Paket-, LLM-/Matrix-/Signalbot-Contract-,
Secret- und pyproject-Pruefungen, waehrend native `signal-cli` Checks lokal
bleiben. Dieser Modus ist absichtlich nicht mit `--skip-adapter-deps`
kombinierbar.

Optionale Live-/Security-Probes bleiben bewusst explizit und nicht blockierend:

```bash
python3 scripts/check_plan2_acceptance.py --list --include-qdrant-live --include-audit
```

Wenn eine alte Klartext-Sicherung vorhanden ist, kann der Runner zusaetzlich nur lesende Recovery-Reports und einen Legacy-Import-Dry-run nach `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming` schreiben:

```bash
python3 scripts/check_plan2_acceptance.py --skip-runtime-status --legacy-instances-dir /home/teladi/TeeBotus_Backups/TeeBotus.bak2
```

Der Legacy-Pfad darf auf einen Backup-Root oder direkt auf einen konkreten `instances*`-Unterordner wie `/home/teladi/TeeBotus_Backups/TeeBotus.bak2/instances.bak` zeigen. Der Recovery-Reporter und Importer waehlen bei Backup-Roots automatisch den besten passenden `instances*`-Unterordner mit Plaintext-User-Memorys.

Hinweis zur Plan2-Testhistorie: Die frueher getrennt geplanten LLM-Basis- und
OpenAI-Provider-Tests sind in der aktuellen Teststruktur zusammengefuehrt.
`tests/test_llm_client.py` deckt die providerneutralen
LLM-Client-/Capability-Primitiven plus LiteLLM-Textadapter ab,
`tests/test_llm_package.py` deckt die oeffentlichen LLM-Paketexports und den
`OpenAIProvider`-Wrapper ab. Der Acceptance-Runner nimmt die aktuellen
Plan2-relevanten `tests/test_*.py`-Module als Quelle der Wahrheit. Im
Standardpfad bleiben Legacy-Import-Unit-Tests bewusst ausgeklammert; mit
`--include-legacy-import-tests` muss der Runner die komplette Repo-Testflaeche
aus `tests/test_*.py` abdecken.

Manuelle Teilchecks:

```bash
python3 -m pytest -q tests/test_runtime_config.py tests/test_llm_config.py
python3 -m pytest -q tests/test_llm_client.py tests/test_llm_package.py tests/test_openai_client.py
python3 -m pytest -q tests/test_litellm_provider.py
python3 -m pytest -q tests/test_bibliothekar_*.py
python3 -m pytest -q tests/test_llm_router.py
python3 -m pytest -q tests/test_pydantic_decisions.py
python3 -m pytest -q tests/test_graphs_*.py
python3 -m pytest -q tests/test_secret_hygiene.py
```

Account-Report:

```bash
python3 -m TeeBotus.admin accounts report --instances-dir instances
```

Der Report liest den AccountStore read-only und erzeugt keine neuen Secrets.
`--runtime-status` meldet zusaetzlich pro Instanz `account_crypto=<Instanz>`
mit `mapping`, `memory`, `pepper` und `keyring`. Diese Zeile zeigt fuer
Secrets nur `present`, `missing_required`, `not_required` oder `error`;
`keyring` meldet `ok`, `partial`, `not_recorded`, `not_required` oder
`broken`. Secret-Werte und Key-Fingerprints werden nicht ausgegeben und ein
Statuslauf erzeugt keine neuen Secrets.
`Account_Keyring.json` enthaelt nur nicht-geheime Key-Fingerprints fuer diese
Instanz-Purposes. Wenn der Desktop Secret Service ploetzlich einen fehlenden
oder anderen Key liefert, stoppt der Store dadurch hart, statt einen neuen
Memory-/Mapping-Key zu erzeugen und alte Memories unlesbar zu machen.
Transienter Secret-Service-Transportfehler (z.B. Timeout waehrend eines
Restarts) wird innerhalb der konfigurierten Lookup-Retrygrenze erneut versucht;
fehlende Eintraege, ungueltige Schluessel und mehrdeutige Secret-Service-Treffer
bleiben harte Fehler.
`account_identity_warning=...` nennt bei Fragmentierungsgefahr auch
`configured_runtime_slots`, `runtime_labels` und `identity_channels`. So ist
sichtbar, ob zum Beispiel `signal:1` konfiguriert ist, aber im AccountStore
nur Telegram-Identities existieren. `action=...` nennt den sicheren naechsten
Schritt: erst in einem bereits verknuepften privaten Chat `/register` oder
`/rotate_secret` nutzen, danach im privaten Zielkanal mit
`/login <account_id> <secret>` verbinden; `/register` im Zielkanal nur, wenn
bewusst ein separater Account entstehen soll.

Wenn `/status` oder `--runtime-status` nicht entschluesselbare
Account-Memory-Payloads oder `account_memory_metadata=... status=broken`
meldet, kann vor jeder Reparatur ein read-only Recovery-Report erzeugt
werden. Metadata-Fehler betreffen Account-Index, Identity-Mapping,
Account-Secrets oder Account-Profile; sie sind keine normalen leeren Memories
und brauchen denselben Recovery-/Quarantaene-Pfad wie kaputte Payloads.

```bash
python3 -m TeeBotus.admin memory-recovery --instances-dir instances
python3 -m TeeBotus.admin memory-recovery --instances-dir instances --format json --output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-memory-recovery.json
```

Der Recovery-Report vergleicht SQLite-Primary, SQLite-Fallback und vorhandene JSON-Dateien pro Account. Er gibt nur Zaehler, Dateipfade und Fehlerklassen aus, keine Secrets und keine rohen Memory-Payloads. Wenn kein Source als `recoverable=True` markiert ist, darf der Bot keine automatische Datenmigration oder Loeschung versuchen; dann fehlt der passende alte Schluessel oder eine lesbare Sicherung.

Wenn eine alte Plaintext-Sicherung mit `instances/<Instanz>/data/users/<telegram_id>/User_Memory_Entries.jsonl` existiert, zaehlt der Recovery-Report diese Quelle zusaetzlich. Wenn die aktuelle Account-Metadaten lesbar sind und `telegram:user:<telegram_id>` bereits auf einen Account zeigt, erscheint sie ausserdem als `legacy_plaintext_user_memory` in den Quellen dieses Accounts und macht den Account im Report `recoverable`.

```bash
python3 -m TeeBotus.admin memory-recovery --instances-dir instances --legacy-instances-dir /home/teladi/TeeBotus_Backups/TeeBotus.bak2
```

Der eigentliche Import ist ein separater, standardmaessig nicht-destruktiver Dry-Run:

```bash
python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /home/teladi/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir instances --replace-unreadable-account-metadata
```

Fuer eine pruefbare Preflight-Akte koennen Markdown und JSON geschrieben werden:

```bash
python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /home/teladi/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir instances --replace-unreadable-account-metadata --json-output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-legacy-import-preflight.json --markdown-output /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/teebotus-legacy-import-preflight.md
```

Der Preflight-Bericht enthaelt `apply_safety`. Vor einem echten Import muss `apply_allowed_now=true`, `apply_requires_stopped_bot=false` und `running_bot_process_count=0` gelten. Wenn dort laufende Prozesse aufgefuehrt sind, zuerst Bot und Proactive-Jobs stoppen und den Preflight erneut schreiben.

Ein echter Import braucht `--apply`. Wenn aktuelle Account-Metadaten nicht entschluesselbar sind, sichert `--replace-unreadable-account-metadata --apply` den aktiven Account-Store komplett weg: `Account_Keyring.json`, `Account_Index.json`, `Account_Identities.json`, `Account_Secrets.json`, `accounts/`, `Account_Memory.sqlite3`, Fallback-SQLite sowie WAL/SHM. Danach werden neue Account-Mappings aus `telegram:user:<id>` erzeugt und die Legacy-Eintraege verschluesselt in den aktuellen AccountStore geschrieben. Vor diesem Schritt muss der Bot gestoppt sein; das Script verweigert `--apply` standardmaessig, wenn `python -m TeeBotus` oder `teebotus-proactive` noch laufen. Danach `python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix` ausfuehren.

## Verhalten steuern

Das Bot-Verhalten liegt pro Instanz in einer eigenen `Bot_Verhalten.md`:

- `instances/Bote_der_Wahrheit/Bot_Verhalten.md`
- `instances/Depressionsbot/Bot_Verhalten.md`

Gemeinsame Defaults stehen in `ALL_BOTS_DEFAULT.md`. Der Bot laedt diese Datei zuerst und danach die aktive Instanzdatei; Instanzwerte ueberschreiben oder ergaenzen die Defaults. Die lokalen Instanzdateien sind absichtlich per `.gitignore` vom Upload ausgeschlossen, damit keine echten Prompts, Regelwerke oder Secrets veroeffentlicht werden.

Die Datei funktioniert bewusst aehnlich wie eine `AGENTS.md`, aber fuer den laufenden Bot:

- `## Einstellungen` steuert Schalter wie `echo`.
- `## OpenAI` steuert OpenAI-Fallback, Modell und Ausgabeparameter.
- `## Antworten` steuert eingebaute Antworten wie `/start`, `/chatid` und unbekannte Befehle.
- `## Befehle` legt eigene Slash-Befehle an. Eingebaute Befehle wie `/status` haben Vorrang, damit Status, Version und Nutzermemory-Groesse konsistent bleiben.
- `## Prompt` in `ALL_BOTS_DEFAULT.md` wird jeder Instanz zusaetzlich mitgegeben.
- `## Securityantworten` in `ALL_BOTS_DEFAULT.md` steuert editierbare Antwortvorlagen fuer Datenschutz- und Security-Fragen.
- `EASTER_EGGS.json` enthaelt auslagerbare Easter-Egg-Antworten, aktuell `security.easter_egg`.
- `## Systemprompt` steuert die Rolle und den Antwortstil des OpenAI-Modells.
- `## Textantworten` beantwortet exakte Texte ohne Slash-Befehl.
- `## Enthaelt` beantwortet Nachrichten, die einen bestimmten Text enthalten.
- `## Hilfe` steuert die Ausgabe von `/help`.

Der Bot laedt die aktive `Bot_Verhalten.md` automatisch neu, sobald sich die Datei geaendert hat und ein neues Telegram-Update ankommt.
Wenn ein Wert am Anfang oder Ende Leerzeichen behalten soll, setze ihn in Anfuehrungszeichen, zum Beispiel `echo_prefix: "Echo: "`.

Du kannst eine andere Instanz oder eine konkrete Datei verwenden:

```bash
TELEGRAM_BOT_INSTANCE=Depressionsbot python3 -m TeeBotus
```

```bash
TELEGRAM_BOT_INSTRUCTIONS=/pfad/zur/datei.md python3 -m TeeBotus
```

Token-Aufloesung:

- `TELEGRAM_BOT_TOKEN_BOTE_DER_WAHRHEIT` fuer `Bote_der_Wahrheit`
- `TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT` fuer `Depressionsbot`
- `TELEGRAM_BOT_TOKEN` als allgemeiner Fallback fuer Einzelbetrieb

Mehrere Telegram-Botnamen pro Instanz:

- `TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT=token_a,token_b` startet Depressionsbot mit mehreren BotFather-Tokens.
- Alternativ gehen nummerierte Variablen wie `TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_2`.
- Nummerierte Variablen sind echte Slotnummern: `_2` belegt Slot 2, darf keinen vorhandenen Listenwert ueberschreiben und darf keine Luecke zu Slot 1 lassen.
- Positionsgebundene Slotlisten duerfen keine leeren Felder enthalten; `token_a,,token_c` ist ein Konfigurationsfehler, weil es Slotzuordnungen verschieben wuerde.
- Alle Tokens einer Instanz nutzen dieselbe aktive `Bot_Verhalten.md` und denselben lokalen User-Speicher.
- Jeder Telegram-Token-Slot braucht bei mehreren Botnamen einen eigenen OpenAI-Key im passenden Slot.

OpenAI-Key-Aufloesung:

- `OPENAI_API_KEY_BOTE_DER_WAHRHEIT` fuer `Bote_der_Wahrheit`
- `OPENAI_API_KEY_DEPRESSIONSBOT` fuer `Depressionsbot`
- `OPENAI_API_KEYS_DEPRESSIONSBOT=key_a,key_b` koppelt Slot 1 an `TELEGRAM_BOT_TOKENS_DEPRESSIONSBOT` Slot 1 und Slot 2 an Telegram-Slot 2
- `OPENAI_API_KEY_DEPRESSIONSBOT_2` koppelt einen nummerierten zweiten OpenAI-Key an `TELEGRAM_BOT_TOKEN_DEPRESSIONSBOT_2`
- `OPENAI_API_KEY` als allgemeiner Fallback nur im Einzelbetrieb

Wenn eine Instanz mehrere Telegram-Tokens startet, verweigert der Bot den Start, falls ein passender OpenAI-Key fehlt oder zwei Telegram-Slots denselben OpenAI-Key verwenden.

## LLM-Router und Providerprofile

OpenAI bleibt als Legacy-Provider fuer Responses, Voice, Bilder, Tool-Calls und Transkription erhalten. Fuer Textantworten gibt es zusaetzlich eine neutrale LLM-Schicht mit `TeeBotus/llm/base.py`, `TeeBotus/llm/openai_provider.py`, `TeeBotus/llm/litellm_provider.py` und Profilrouting unter `config/`.

Die zentralen Profil-Dateien sind:

- `config/llm_profiles.yaml`
- `config/llm_routing.yaml`

Vorbereitete Profile decken lokale und Remote-Provider ab, unter anderem Ollama, Hugging Face, Groq, Gemini, Vertex AI und OpenAI-kompatible LiteLLM-Modelle. Remote-Fallbacks sind standardmaessig aus. Ein Fallback auf ein Remote-Profil wird nur genutzt, wenn der jeweilige Codepfad explizit `allow_remote_fallback=True` setzt.

Admins koennen mit `/RouteTo<Ziel> <Prompt>` einen Prompt direkt an ein LLM-Backendprofil oder eine konfigurierte Route schicken, ohne User-Memory, Wetter, Bibliothekar-Kontext oder normalen Bot-Prompt davorzuschalten. Ohne Prompt setzt `/RouteTo<Ziel>` eine einmalige Route fuer die naechste Nachricht; `/cancel` bricht sie ab. Ziele werden ueber Aliase und Profilnamen aufgeloest, z.B. `/RouteToOpenAI`, `/RouteToOAI`, `/RouteToHF`, `/RouteToHFPool`, `/RouteToGemini`, `/RouteToOllama`, `/RouteToGroq`, `/RouteToVertex` oder direkt `/RouteToGeminiFlashStateful`. Auch Purposes aus `config/llm_routing.yaml` funktionieren, z.B. `/RouteToStructuredDecision`.

Zusaetzlich gibt es einen optionalen `hf_pool`-Provider unter `TeeBotus/llm/hf_pool/`. Er ist lazy, non-fatal und nicht Default: fehlende oder deaktivierte `config/hf_pool.yaml`-Ziele erscheinen im Doctor/Runtime-Status, brechen aber den Botstart nicht. Fallbacks greifen nur, wenn der Router sie explizit durch `allow_remote_fallback=True` erlaubt; Standardtests nutzen den MockExecutor nur per expliziter Test-Injektion. Der Runtime-Provider mockt konfigurierte Targets nicht automatisch: ohne explizit aktivierten Live-Executor liefert er kontrolliert `hf_pool unavailable` und nutzt gegebenenfalls den erlaubten Fallback. `OpenAICompatibleHFPoolExecutor` kann OpenAI-kompatible HF-Chat-Completions ausfuehren, ist aber nur per `TEEBOTUS_HF_POOL_LIVE=1` oder `TEEBOTUS_HF_POOL_EXECUTOR=live` aktiv und bringt Token-Redaction, optionalen SQLite-Cooldown-State und Usage Events mit. `TEEBOTUS_HF_POOL_STATE_DB=/pfad/hf_pool_state.sqlite3` ueberschreibt den lokalen State-Pfad. Live-Hugging-Face-Tests muessen explizit aktiviert werden.
Die vorbereitete, deaktivierte Modellmatrix deckt `normal_chat`,
`structured_decision`, `psychology_explainer`, `bibliothekar_answer` und
`summarizer` ab.

```bash
python3 -m TeeBotus.llm.hf_pool.doctor
python3 -m TeeBotus.llm.hf_pool.doctor --live
python3 -m TeeBotus.llm.hf_pool.doctor --live --state-db ~/.local/state/teebotus/hf_pool_state.sqlite3
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_hf_pool_live.py
```

`--live` versucht nur dann echte HF-Requests, wenn Pool und Ziel in `config/hf_pool.yaml`
aktiviert sind und der benoetigte Token im Environment steht. Der Live-Doctor meldet
pro Ziel `healthy`, `cooldown`, `unavailable` oder `error`, redigiert HF-Tokens und
kann Cooldowns/Usage in einer SQLite-State-DB festhalten.
Der Live-Pytest skippt ohne `TEEBOTUS_LIVE_HF=1` und prueft mit aktivem Target,
dass Usage und Latenz in einer temporaeren SQLite-State-DB landen.

Zur Laufzeit kann ein konkretes Profil ueber `profile: ...` in `Bot_Verhalten.md` oder ueber `TEEBOTUS_LLM_PROFILE_<INSTANZ>` und kanalspezifische Varianten gesetzt werden. Telegram, Signal und Matrix bauen ihren Text-LLM-Client dann aus diesem Profil; ohne Profil bleibt das bisherige direkte Provider-/OpenAI-Verhalten erhalten.

Die effektive Reihenfolge ist bewusst eindeutig: ein explizites Runtime-Profil (`TEEBOTUS_LLM_PROFILE...`) gewinnt immer. Wenn kein Runtime-Profil gesetzt ist, gewinnen explizite Runtime-Routen (`TEEBOTUS_LLM_PURPOSE...`, `TEEBOTUS_LLM_PROVIDER...`, `TEEBOTUS_LLM_MODEL...`) gegen ein Profil aus `Bot_Verhalten.md`. Nur wenn keine solche Runtime-Route gesetzt ist, wird `profile: ...` aus `Bot_Verhalten.md` verwendet. Danach folgen direkte `provider`-/`model`-Werte aus `Bot_Verhalten.md` und zuletzt der OpenAI-Legacy-Pfad.

Die aktiven Instanzwerte kommen aus `Bot_Verhalten.md` oder Environment. Neue neutrale Felder sind:

```text
## LLM
- enabled: ja
- provider: litellm
- model: ollama_chat/llama3.1:8b
- profile: local_ollama
- base_url: http://127.0.0.1:11434
- timeout_seconds: 120
- max_tokens: 1200
- temperature: 0.7
- missing_key: Das Textmodell ist aktiviert, aber der benoetigte API-Key fehlt.
- error: Ich kann das Textmodell gerade nicht erreichen.
- reset: Der Text-LLM-Kontext fuer diesen Chat wurde geloescht.
```

`missing_key`, `error` und `reset` im `## LLM`-Block steuern nur Text-LLM-Antworten und den per `/reset` geloeschten Text-LLM-Kontext. OpenAI-spezifische Spezialfunktionen wie Voice, Bilder und OpenAI-Transkription behalten ihre eigenen `openai_*`-/`voice_*`-/`image_*`-/`transcription_*`-Texte. Alte `## OpenAI - missing_key/error/reset`-Eintraege bleiben kompatibel und setzen die Text-LLM-Texte mit, sofern sie nicht im `## LLM`-Block ueberschrieben werden.

Environment-Fallbacks heissen `TEEBOTUS_LLM_ENABLED`, `TEEBOTUS_LLM_PROVIDER`, `TEEBOTUS_LLM_MODEL`, `TEEBOTUS_LLM_PROFILE`, `TEEBOTUS_LLM_PURPOSE`, `TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK`, `TEEBOTUS_LLM_BASE_URL`, `TEEBOTUS_LLM_API_KEY`, `TEEBOTUS_LLM_TIMEOUT_SECONDS`, `TEEBOTUS_LLM_MAX_OUTPUT_TOKENS` und `TEEBOTUS_LLM_TEMPERATURE`; instanz-, kanal- und slot-spezifische Varianten werden ebenfalls aufgeloest. Alte `openai_*`-Felder bleiben kompatibel.

`TEEBOTUS_LLM_PURPOSE` wird tolerant normalisiert: Gross-/Kleinschreibung ist egal, Leerzeichen und Bindestriche werden zu Unterstrichen. `Structured Decision`, `structured-decision` und `structured_decision` routen also auf denselben Eintrag in `config/llm_routing.yaml`.

`--runtime-status` gibt zusaetzlich eine `llm_route=structured_decision`-Zeile
aus. Sie zeigt den typisierten Decision-Provider, das Profil, den effektiven
Fallback und ob die Route aktuell wirklich verfuegbar ist; ein deaktivierter
oder nicht schluesselfaehiger `hf_pool` erscheint dort als `status=unavailable`.
Daneben erscheint pro Runtime-Account eine `structured_decision=<Instanz>/<Slot>`-
Zeile. Sie zeigt, ob strukturierte Subtasks fuer diese Instanz wirklich aktiv
sind, ob sie dem Text-LLM-Schalter folgen oder per
`structured_decision_enabled` explizit gesteuert werden, und welchen
Fallbackpfad der Runner nutzen wuerde.

Ollama Quickstart:

```bash
ollama serve
ollama pull llama3.1:8b
TEEBOTUS_LLM_PROVIDER=litellm \
TEEBOTUS_LLM_MODEL=ollama_chat/llama3.1:8b \
TEEBOTUS_LLM_BASE_URL=http://127.0.0.1:11434 \
python3 -m TeeBotus --runtime-status --channels telegram
```

Remote-Profile werden genauso per Profil geschaltet. `gemini_flash_stateless`
und `gemini_flash_stateful` erwarten `GEMINI_API_KEY`; die bezahlten Varianten
nutzen dieselbe Key-Variable, haben aber keine Free-Tier-Drossel. `vertex_gemini_flash`
erwartet `GOOGLE_APPLICATION_CREDENTIALS` als Pfad auf lokale
Vertex/Google-Credentials. `gemini_flash_stateful` nutzt den
LiteLLM-Gemini-Stateful-Client (`provider=litellm_gemini_stateful`) mit
`store=true` und `previous_interaction_id`; alte Aliase wie
`gemini_interactions` werden darauf normalisiert. `gemini_flash_stateless` und
Vertex-Gemini ueber LiteLLM bleiben stateless; TeeBotus sendet dort den
benoetigten lokalen Kontext selbst und verlaesst sich nicht auf serverseitige
Google-Conversation-State.

Gemini/Vertex-Service-Tier:

```bash
TEEBOTUS_GEMINI_SERVICE_TIER=flex
TEEBOTUS_GEMINI_SERVICE_TIER_DEPRESSIONSBOT=flex
TEEBOTUS_GEMINI_FLEX_SERVICE_TIER_DEPRESSIONSBOT=yes
TEEBOTUS_LLM_SERVICE_TIER_DEPRESSIONSBOT=flex
```

Der Wert wird nur bei Google-Gemini/Vertex-Modellen an LiteLLM uebergeben. Fuer
Ollama, Groq, Hugging Face und lokale Fallbacks wird `service_tier` nicht in den
Provider-Call geschrieben. In `Bot_Verhalten.md` kann derselbe Schalter im
`## LLM`-Block als `service_tier: flex` stehen; im `## OpenAI`-Block bleibt
`service_tier: flex` weiterhin der bestehende OpenAI-Responses-Schalter.

Gemini-Keyrotation:

```bash
TEEBOTUS_LLM_PROFILE_DEPRESSIONSBOT=gemini_flash_stateful
GEMINI_API_KEYS_ACCOUNT_1=acc1_key1,acc1_key2,acc1_key3
GEMINI_API_KEYS_ACCOUNT_2=acc2_key1,acc2_key2,acc2_key3
GEMINI_API_KEYS_ACCOUNT_3=acc3_key1,acc3_key2,acc3_key3
```

Google wendet Gemini-Rate-Limits pro Projekt an, nicht pro API-Key. Die
Keyring-Eintraege muessen deshalb Projekt-Keys sein: pro Google-Projekt genau
ein Key. Mehrere Keys aus demselben Projekt erhoehen die Quote nicht und wuerden
den lokalen Guard nur falsch zaehlen lassen. Der Bot verwebt diese Buckets
spaltenweise:
`acc1_project1, acc2_project1, acc3_project1, acc1_project2, acc2_project2, acc3_project2, ...`.
Trifft ein Gemini/LiteLLM-Aufruf auf `429`, `RESOURCE_EXHAUSTED`, Quota- oder
Usage-Limit, springt der Client im laufenden Prozess auf den naechsten Key.
Normale Provider-/Netzwerkfehler rotieren den Key nicht. Alternativ kann die
fertig sortierte Liste direkt ueber `GEMINI_API_KEY_RING` oder
`TEEBOTUS_GEMINI_API_KEY_RING` gesetzt werden; instanzspezifisch sind
`TEEBOTUS_GEMINI_API_KEYS_<INSTANZ>_ACCOUNT_N` und
`TEEBOTUS_GEMINI_API_KEY_RING_<INSTANZ>` moeglich.

Gemini-/Vertex-Free-Tier-Guard:

```bash
TEEBOTUS_GEMINI_FREE_TIER_RPM=5
TEEBOTUS_GEMINI_FREE_TIER_TPM=250000
TEEBOTUS_GEMINI_FREE_TIER_RPD=20
TEEBOTUS_GEMINI_FREE_TIER_RESERVE_TOKENS=2048
TEEBOTUS_GEMINI_FREE_TIER_REFRESH_ENABLED=true
TEEBOTUS_GEMINI_FREE_TIER_REFRESH_INTERVAL_SECONDS=86400
TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL=https://ai.google.dev/gemini-api/docs/rate-limits
```

Der Guard zaehlt pro Projekt-Key Requests/min, geschaetzte Input-Tokens/min und
Requests/Tag. Wenn ein Request kurz vor dem Limit die Reserve verletzen wuerde,
wird der Provider-Aufruf uebersprungen und beim Keyring der naechste Projekt-Key
versucht. Sind alle Projekt-Keys lokal erschoepft, bricht der LLM-Aufruf sauber
ab, statt absichtlich in einen Google-429 zu laufen. Die konkreten Free-Tier-
Werte koennen sich je Modell und Projekt aendern; die Werte sollten deshalb aus
AI Studio/Projektquoten uebernommen werden.

Beim Bot-Start laeuft fuer Gemini/Vertex-Konfigurationen ein Hintergrundjob,
der hoechstens einmal pro Tag (`TEEBOTUS_GEMINI_FREE_TIER_REFRESH_INTERVAL_SECONDS`,
Default `86400`) eine Limit-Quelle abruft und unter
`TEEBOTUS_GEMINI_FREE_TIER_CACHE` oder
`~/.cache/teebotus/gemini_free_tier_limits.json` speichert. Die Default-Quelle
ist die offizielle Gemini-Rate-Limit-Seite. Google weist dort darauf hin, dass
aktive Limits projekt- und tierabhaengig in AI Studio sichtbar sind und
veroeffentlichte Werte nicht garantiert sind; deshalb ueberschreibt TeeBotus den
Cache nur, wenn die Quelle eine parsebare Free-Tier-Tabelle oder JSON mit
`rpm`/`tpm`/`rpd` pro Modell liefert. Ein eigener AI-Studio-/Quota-Export kann
ueber `TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL` angebunden werden. Effektive
Prioritaet: explizite Env-Werte > frisch gecachte Werte > konservative Defaults.

Instanzspezifisch funktionieren
`TEEBOTUS_GEMINI_FREE_TIER_<INSTANZ>_RPM`, `_TPM`, `_RPD`,
`_RESERVE_TOKENS` und `_ENABLED`. `none`/`unlimited` deaktiviert eine einzelne
Dimension, `TEEBOTUS_GEMINI_FREE_TIER_ENABLED=false` schaltet den Guard ab.
`--runtime-status` meldet Google-Routen als `google_mode=stateful`, wenn sie
ueber `litellm_gemini_stateful`, `litellm_gemini_paid_stateful` oder einen
darauf normalisierten Alias wie `gemini_interactions` laufen, sonst weiter als
`google_mode=stateless`.
Bei aktiviertem Schalter erscheinen `service_tier=flex`, die wirksamen
Guard-Werte als `free_tier_guard=...` und der Cachezustand als
`gemini_free_tier_limits status=...`.

Die Gemini/Vertex Live API ist weiterhin ein separater WebSocket-/GenAI-SDK-
Pfad fuer Echtzeit-Audio, Video und Text. Stateful Gemini-Text laeuft hier ueber
die Interactions API, nicht ueber Live API.

`--runtime-status` nutzt dieselbe effektive LLM-Aufloesung wie der Bot-Start. Er beruecksichtigt also `Bot_Verhalten.md`, Runtime-Overrides und deaktivierte LLMs gleich wie die Runtime-Fabrik. Lokale Ollama-Targets werden nur fuer effektiv aktive Ollama-Konfigurationen geprueft und melden gefundene Modelle. Ollama ist der bevorzugte lokale Textprovider; Voice, Bilder und OpenAI-spezifische Tool-Calls bleiben beim OpenAI-Client, solange dafuer kein lokales Pendant angebunden ist.

Remote-Profile und Remote-Fallbacks werden im Status als `missing_key` oder
`degraded` gemeldet, wenn der benoetigte Primaer- oder Fallback-Key fehlt.
Lokale Ollama- und loopback-LiteLLM-Ziele bleiben ohne Key gueltig.

LiteLLM-Security:

- `litellm` ist gepinnt und die bekannten kompromittierten Versionen `1.82.7` und `1.82.8` sind blockiert.
- `scripts/check_adapter_deps.py` prueft den Pin, blockierte Versionen und verdächtige `litellm*.pth`-Dateien.
- Keine Provider-Keys gehoeren ins Repo; nutze `.env`, Secret-Service oder lokale systemd-Environment-Dateien.

Rollback:

- Setze `llm_enabled: nein` oder entferne den `## LLM`-Block, um zur bisherigen OpenAI-/Regelantwort-Logik zurueckzukehren.
- Setze `TEEBOTUS_LLM_ENABLED_<INSTANZ>=false`, um Text-LLM-Antworten per Runtime-/systemd-Override hart abzuschalten; `--runtime-status` meldet dann `provider=none status=disabled`.
- Setze `llm_provider: openai`, `TEEBOTUS_LLM_PROVIDER_<INSTANZ>=openai` oder entferne `TEEBOTUS_LLM_MODEL_<INSTANZ>`/`TEEBOTUS_LLM_BASE_URL_<INSTANZ>`, wenn Textantworten wieder ueber den OpenAI-kompatiblen Legacy-Pfad laufen sollen.
- Entferne `TEEBOTUS_LLM_*`-Overrides aus der Shell oder systemd-Unit, wenn unerwartet ein falsches Profil gewaehlt wird.
- Pruefe den schnellen OpenAI-Rollback danach mit `python3 -m TeeBotus --runtime-status --channels telegram`; der Status muss fuer die betroffene Instanz wieder `provider=openai` oder den deaktivierten Providerzustand melden.
- Git-Rollback bleibt normaler Git-Betrieb: auf einen bekannten Commit/Tag wechseln und danach mindestens `python3 -m TeeBotus --runtime-status --channels telegram` sowie die relevanten Tests ausfuehren. Vor einem harten Reset erst `git status --short --branch` pruefen und lokale Datenbackups getrennt sichern.
- Daten-Rollback betrifft nur nicht rebuildbare Daten: `.env`, Instanzkonfiguration und verschluesselte AccountStore-/Memory-Dateien. Bibliothekar-/Haystack-/Qdrant-Indizes sind rebuildbar und sollen aus `instances/<Instanz>/data/Bibliothek` neu erzeugt werden.
- Fuer einen Service-Rollback: Dienst stoppen, Backup von `instances/` und `.env` zuruecklegen, dann Dienst starten und `python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix` ausfuehren. Wenn Account-Memory danach `broken` meldet, nicht automatisch loeschen, sondern zuerst mit `python3 -m TeeBotus.admin memory-recovery --instances-dir instances --instances <Instanz>` analysieren.

Unterstuetzte Platzhalter in Antworten:

- `{first_name}`
- `{last_name}`
- `{username}`
- `{name_suffix}`
- `{chat_id}`
- `{text}`

Freie normale Nachrichten gehen nur dann an OpenAI, wenn:

- `## OpenAI` den Wert `enabled: true` enthaelt,
- der passende OpenAI-Key fuer die aktive Instanz beziehungsweise den aktiven Telegram-Token-Slot gesetzt ist,
- keine Regel aus `## Textantworten` oder `## Enthaelt` passt.

Bei OpenAI-Nachrichten sendet der Bot zusaetzlich Telegram-Metadaten mit: Chat-ID, Chat-Typ, Chat-Titel, Absender-ID, Absendername und Username. Dadurch kann das Modell in Gruppenchats Nutzer auseinanderhalten.

## Bot-Namen

Jeder Telegram-Token hat eine eigene Telegram-Identitaet. Der Bot ruft beim Start `getMe` auf und kennt dadurch `first_name` und `username` dieses BotFather-Bots.

In Gruppen muss ein neuer User den Bot beim ersten Kontakt mit diesem offiziellen Namen, dem leserlichen Namen oder dem `@username` ansprechen. Eine Reply auf eine Bot-Nachricht zaehlt ebenfalls. Beim ersten echten Kontakt meldet sich der Bot mit diesem Namen, zum Beispiel `Ich bin Bote der Wahrheit.`

Sobald dieser User mit diesem Bot bekannt ist, darf der User ihn beliebig nennen. Die Zuordnung laeuft dann ueber die erkannte Telegram-Identity, die Account-ID und das Account-Memory.

Feste Slash-Befehle werden nicht an OpenAI gesendet.

`/Call_a_Teladi` ist ein fester Notfallbefehl. Der Bot fragt nach, welche Emergency Message weitergeleitet werden soll, sendet einen kurzen Herkunfts-Header an Teladi und kopiert danach die naechste Telegram-Nachricht unveraendert dorthin. Pro Account kann der Befehl nur einmal innerhalb von 24 Stunden ausgeloest werden; weitere Versuche werden mit Restzeit abgelehnt. Ohne AccountStore faellt der Cooldown auf die erkannte Telegram-Identity zurueck. Der Cooldown wird im lokalen Instanz-`data`-Ordner gespeichert und uebersteht Bot-Neustarts. Der interne Zielchat wird Usern nicht angezeigt.

Lange OpenAI-Antworten werden automatisch in mehrere Telegram-Nachrichten aufgeteilt, damit Telegrams Nachrichtenlimit nicht erreicht wird.

Sprachnachrichten werden mit `/voice Text` erzeugt. Alternativ kannst du auf eine Textnachricht antworten und nur `/voice` senden; der Bot vertont dann den Text der beantworteten Nachricht. Die Default-Stimme wird in der aktiven Instanz-`Bot_Verhalten.md` ueber `voice_model`, `voice`, `voice_format`, `voice_speed` und `voice_instructions` gesteuert. Nutzer koennen mit `/voicemodel <stimme>` eine eigene OpenAI-Stimme waehlen, zum Beispiel `/voicemodel onyx`; `/voicemodel reset` nutzt wieder den Instanz-Default. Mit `/mimic_voice on` kann ein aus eigenen Sprachnachrichten abgeleitetes Sprechweisen-Profil fuer TTS genutzt werden; `/mimic_voice before` setzt diese Anweisung vor den Dialekt, `/mimic_voice after` danach, `/mimic_voice reset` loescht das Profil. Die aktuelle OpenAI-Voice-Liste steht unter https://platform.openai.com/docs/guides/text-to-speech#voice-options. Standard ist `voice_format: opus`, passend fuer Telegram-Sprachnachrichten.

`/codex Prompt` startet den lokalen Codex-CLI-Prozess aus dem Bot-Prozess heraus. Zugelassen sind nur die in der aktiven Instanz-`Bot_Verhalten.md` unter `## Codex` eingetragenen Account-IDs, zum Beispiel `allowed_account_ids: <128-hex-account-id>`. Telegram-Sender-IDs reichen dafuer nicht mehr. Der Bot arbeitet dabei aus dem Repository-Root und benutzt kein `shell=True`.

Automatische Sprachnachrichten werden in der aktiven Instanz-`Bot_Verhalten.md` ueber `auto_voice_enabled`, `auto_voice_every`, `auto_voice_max_words` und `auto_voice_skip_sources` gesteuert. Aktuell wird jede dritte OpenAI-Antwort unter 50 Woertern ohne Quellen als Sprachnachricht gesendet.

Eingehende Sprachnachrichten werden transkribiert und danach durch dieselbe Textlogik geschickt wie normale Nachrichten. Gesteuert wird das in der aktiven Instanz-`Bot_Verhalten.md` ueber `transcription_enabled`, `transcription_backend`, `local_transcription_model`, `transcription_model`, `transcription_fallback_model`, `transcription_language`, `transcription_prompt`, `transcription_error` und `transcription_empty`. Mit `transcription_backend: local` nutzt der Bot lokal `faster-whisper` oder die `whisper` CLI und faellt nicht auf OpenAI zurueck. Mit `transcription_backend: openai` nutzt er die OpenAI-Transkription; nur in diesem Modus versucht er bei leerem Ergebnis einmal `transcription_fallback_model`, wenn dieses Feld gesetzt und vom Primaermodell verschieden ist. Der transkribierte Inhalt wird nicht in die stdout-Logs geschrieben. Audio-Dateien werden nicht gespeichert; im User-Memory landet nur das Transkript als Text.

YouTube-Transkripte laufen zweistufig: Zuerst versucht der Bot mit `yt-dlp` vorhandene YouTube-Untertitel zu laden. Wenn keine Untertitel gefunden werden, fragt er vor lokaler Transkription nach Live-Ausgabe und LLM-Weitergabe. Lokale Transkription laeuft ueber `faster-whisper` mit Modell `tiny`, automatischer Sprachwahl fuer Deutsch/Englisch, maximal zwei CPU-Threads, `nice -n 19` und, falls vorhanden, `ionice -c 3`. Der lokale Transkriptionsjob laeuft in einem Hintergrund-Worker; Telegram-Polling bleibt aktiv. Timeout ist `7200` Sekunden. Nach 5, 15, 60 und 90 Minuten prueft ein Watchdog, ob der Child-Prozess noch plausibel lebt. Wenn nicht, beendet der Bot die Prozessgruppe und meldet den Fehler im Chat. Reine Python-`resource_tracker`-Warnungen beim Abbruch werden aus dem Telegram-Fehlertext herausgefiltert.

Wenn der Freitext-Parser Live-Ausgabe oder LLM-Weitergabe nicht vollstaendig erkennt und `youtube_option_llm_fallback: ja` gesetzt ist, kann ein vorhandener OpenAI-/LLM-Client die beiden Optionen eng als JSON klassifizieren. Parser-Ergebnisse gewinnen dabei; das LLM fuellt nur fehlende Werte. Solche nachtraeglich erkannten Formulierungen werden URL-redaktiert in `instances/{instance}/data/YouTube_Parser_Misses.jsonl` protokolliert und instanzlokal wieder vom Parser gelesen, damit dieselbe Formulierung beim naechsten Mal ohne LLM-Fallback erkannt wird. Der Wiedererkennungsabgleich ist konservativ tokenbasiert und ignoriert URL- und Befehlsfuelltext, verlangt aber mehrere spezifische Tokens.

Die zaehlbaren Grundformen des Live/LLM-Parsers koennen mit `python3 scripts/youtube_parser_stats.py` oder maschinenlesbar mit `python3 scripts/youtube_parser_stats.py --json` neu berechnet werden. Die konkrete Sprache bleibt wegen freier Regex-Zwischenraeume und Learned-Phrases offen; das Skript weist deshalb eine konservative zaehlbare Untergrenze aus. Ein LLM-Fallback zur Klassifikation unklarer Live/LLM-Optionen ist aus Kostengruenden standardmaessig aus und muss in `Bot_Verhalten.md` explizit mit `youtube_option_llm_fallback: ja` aktiviert werden.

Der aktuelle Bestand gelernter Parser-Misses kann mit `python3 scripts/youtube_parser_misses_report.py --instances-dir instances` ausgewertet werden. Der Report gruppiert Formulierungen, zeigt ob der Basisparser sie inzwischen direkt erkennt, markiert verbleibende Kandidaten fuer dauerhafte Parser-Regeln und gibt pro Kandidat eine kompakte Promotion-Suggestion mit Zielwerten und spezifischen Tokens aus. Mit `--regression-json` erzeugt der Report eine kompakte Testfall-Liste; mit `--pytest-snippet` erzeugt er direkt einen einfuegbaren `pytest.mark.parametrize`-Block fuer Parser-Regressionen.

## Bibliothekar, Haystack und LangGraph

Der Bibliothekar ist die lokale Instanz-Bibliothek unter `instances/<instance>/data/Bibliothek`. Dort koennen `.pdf`, `.epub`, `.docx`, `.txt`, `.md` und `.markdown` abgelegt werden. Der lokale Store baut daraus `.bibliothekar/index.json` und `.bibliothekar/chunks.jsonl`. Antworten duerfen kurze Abschnitte daraus zitieren und muessen dann Titel, Datei, Locator und `chunk_id` nennen.

Das Bibliothekar-Indexschema speichert pro Dokument und Chunk stabile Quellenmetadaten wie `source_id`, `file_sha256`, `file_type`, `language`, `chunk_index`, `ingested_at` und `embedding_model`; aeltere Cache-Schemas werden beim Zugriff automatisch neu aufgebaut.

Wichtig: Account-Memory wird nicht in Haystack und nicht als Klartext in Qdrant
gespeichert. Account-Memory bleibt getrennt, accountbezogen und
verschluesselt; der `AccountStore` bleibt die Wahrheit. Qdrant darf fuer
Usermemory nur als optionaler, rebuildbarer ID-/Vektor-Cache dienen.
Haystack/Qdrant fuer Bibliotheksdokumente bleibt separat und betrifft Buecher,
Handbuecher, PDFs und andere explizit abgelegte Referenzen.

Konfiguration in `Bot_Verhalten.md`:

```text
## Bibliothekar
- enabled: ja
- backend: local
- collection: teebotus_bibliothekar_chunks
- qdrant_url: http://127.0.0.1:6333
- max_prompt_chars: 5000
- max_chunks: 5
- max_quote_chars: 900
- require_citations: ja
```

`backend: local` nutzt den JSONL-Store. `backend: haystack` oder `backend: qdrant` aktiviert den optionalen Haystack/Qdrant-Backendpfad hinter derselben `BibliothekarService`-Schnittstelle. `backend: llamaindex` aktiviert den lokalen LlamaIndex-Pilot, wenn `llama-index-core` installiert ist. Der lokale Store bleibt dabei die rebuildbare Quelle; Haystack/Qdrant und LlamaIndex sind Backend-/Cache-Schichten fuer produktivere Suche.

Vor dem Bibliothekar-Kontext kann ein optionaler Pydantic-Subtask `BibliothekarQueryDecision` laufen. Er entscheidet, ob der Quellenindex fuer die aktuelle natuerliche Sprache durchsucht werden soll, und kann die Suchfrage knapp normalisieren. Ohne strukturierten Runner bleibt das alte Verhalten erhalten: der Bibliothekar sucht weiter, sobald er in der Instanz aktiviert ist. Fuer echte Pydantic-AI-Laeufe gibt es `TeeBotus.decisions.pydantic_agent.build_router_pydantic_ai_model_runner("structured_decision")`, der den TeeBotus-LLM-Router nutzt und aktuell auf den `hf_pool_structured`-Bucket zeigt. `build_pydantic_ai_model_runner(model)` bleibt fuer direkte Tests/Fakes verfuegbar. Der Adapter ist optional, nutzt Pydantic-AIs strukturierte `output_type`-Ausgabe und meldet klar, wenn das Extra `[agents]` nicht installiert ist.

Wenn ein konfigurierter Structured-Runner selbst fehlschlaegt oder kein validierbares Ergebnis liefert, bleibt die Suche geschlossen: Die Nachricht wird ohne Bibliothekskontext beantwortet. Klassische Treffer wie Buch-, Quellen- oder Zitatfragen umgehen diesen Fallback und suchen weiterhin direkt. Dadurch landen bei einem defekten Decision-Backend keine zufaelligen oder irrelevanten Chunks im Prompt.

CLI:

```bash
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot status
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot index --source /pfad/zu/buechern --dry-run
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot index --source /pfad/zu/buechern
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot harvest /pfad/zu/quelle.pdf --title "Quelle" --license private
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot promote instances/Depressionsbot/data/Bibliothek/accepted/<sha>-quelle.pdf
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot query "Was steht zu Schlaf und Aktivierung?" --top-k 3
python3 -m TeeBotus.bibliothekar --instance Depressionsbot query --source tests/fixtures/books "Schlafhygiene Tagesstruktur" --top-k 3
python3 -m TeeBotus.bibliothekar --instance Depressionsbot query "System Therapie" --category psychologie --topic schlafhygiene --file therapie --extension txt
```

`harvest` schleust lokale Quellen zuerst durch das SourceQuality-Gate, schreibt Manifest und SHA-256-Dedupe und legt die Datei je nach Entscheidung unter `accepted/`, `quarantine/` oder `rejected/` ab. Die Harvest-Verzeichnisse `inbox/`, `accepted/`, `quarantine/` und `rejected/` sind Staging-Bereiche und werden vom normalen Bibliothekar-Rebuild nicht indexiert; akzeptierte Dateien werden nur als `accepted_for_ingest` markiert. Erst `promote` kopiert eine akzeptierte Staging-Datei bewusst nach `books/`, wo sie beim naechsten `index`/Rebuild erfasst wird.
`query --source` baut einen temporaeren lokalen Fixture-Index und veraendert die echte Instanz-Bibliothek nicht. Das ist fuer Akzeptanztests und Benchmarkvergleiche gedacht.
`query` kann mit `--category`, `--topic`/`--keyword`, `--file`/`--relative-path`, `--extension` und `--suffix` auf indexierte Metadaten eingeschraenkt werden; dieselben Filter laufen ueber den lokalen Store und das Haystack/Qdrant-Backend.

Haystack/Qdrant/LlamaIndex optional:

```bash
python3 -m pip install '.[rag]'
qdrant --host 127.0.0.1 --port 6333
teebotus-qdrant-systemd --print
teebotus-qdrant-systemd --enable
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot status
```

`teebotus-qdrant-systemd` erzeugt eine User-systemd-Unit fuer Podman, bindet Qdrant
nur an `127.0.0.1:6333`, nutzt das Volume `teebotus-qdrant:/qdrant/storage` und
verwendet einen gepinnten `qdrant/qdrant`-Image-Tag statt `latest`.

Der allgemeine Qdrant-Sockel ist optional und nicht startkritisch. `TEEBOTUS_QDRANT_URL`
defaultet auf `http://127.0.0.1:6333`; `--runtime-status` meldet auch ohne
Bibliothekar-Qdrant-Backend eine Zeile wie
`qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search`.
Direkt darunter erscheinen die nicht-mutierenden Collection-Diagnosen
`qdrant_collection=teebotus_user_memory ...` und
`qdrant_collection=teebotus_bibliothekar_chunks ...`; bei unerreichbarem Qdrant
zeigen sie die geplanten Namen, Dimensionen und Embedding-Modelle, ohne
Collections anzulegen.
Die vorbereiteten Collection-Namen sind `teebotus_user_memory` und
`teebotus_bibliothekar_chunks`. Usermemory nutzt die vorhandene lokale
semantische Cache-Dimension, Bibliothekar-Chunks sind fuer
`BAAI/bge-m3` vorbereitet.
Die Embedding-Schicht liegt unter `TeeBotus.embedding`: `EmbeddingProvider`
unterstuetzt `embed_text` und Batch-`embed_texts`, `FakeEmbeddingProvider`
bleibt der lokale Teststandard, `HFEmbeddingProvider` kann per injiziertem
HTTP-Opener/HF-Endpoint Feature-Extraction oder TEI/OpenAI-aehnliche Embedding-
Payloads verarbeiten. `KeywordRerankerProvider` und `check_embedding_provider`
decken den lokalen Reranker-/Health-Sockel ab.
`TeeBotus.runtime.qdrant_memory.QdrantMemoryIndex` ist ein opt-in Cache:
AccountStore bleibt die Wahrheit, `index_memory`, `search`, `delete_memory`,
`delete_account` und `rebuild` schreiben nur Vektoren, `schema`,
`schema_version`, `instance_name`, einen abgeleiteten `account_scope`,
`memory_id` und Embedding-Metadaten nach Qdrant, keine rohe `account_id`, keine
`user_text`-/`bot_text`-/Keyword-Klartexte, keine klinischen Kategorien,
Scores, Zeitangaben, Content-/Keyword-Hashes oder Messenger-Identitaeten.
`TeeBotus.runtime.memory_search.MemorySearchService` merged lokale
Keyword-/Metadaten-Kandidaten aus `KeywordMemorySearch` mit optionalen
Qdrant-Kandidaten aus `QdrantMemorySearch`. Ohne explizite Config bleibt die
lokale Suche Standard; semantische Qdrant-Suche ist nur mit
`## Memory Search` in `Bot_Verhalten.md` aktiv, zum Beispiel:

```markdown
## Memory Search
- semantic_enabled: true
- semantic_backend: qdrant
- local_limit: 8
- semantic_limit: 8
- embedding_provider: hash
- embedding_model: teebotus-account-memory-hash
- embedding_dimensions: 64
```

`embedding_provider: hash` bleibt komplett lokal und ist der sichere Default.
Fuer echte lokale semantische Embeddings kann derselbe Pfad explizit auf einen
lokalen HF-/TEI-kompatiblen Endpoint zeigen:

```markdown
## Memory Search
- semantic_enabled: true
- semantic_backend: qdrant
- embedding_provider: tei
- embedding_model: intfloat/multilingual-e5-small
- embedding_dimensions: 384
- embedding_endpoint: http://127.0.0.1:8080/embeddings
- embedding_api_key_env: HF_TOKEN
```

Fuer Account-Memory sind nur der lokale Hash-Provider, lokale
`sentence-transformers`-Modelle oder explizit lokale HTTP-Embedding-Endpoints
erlaubt (`127.0.0.1`, `localhost` oder `::1` mit Port). `hf`/`tei` ohne
Endpoint faellt nicht auf die Hugging-Face-API zurueck, sondern wird fuer
Usermemory blockiert, damit verschluesselte Erinnerungen nicht still als
Embedding-Input an Remote-Provider gehen. `sentence-transformers` laedt
Account-Memory-Modelle standardmaessig nur aus dem lokalen Cache.

Qdrant liefert dabei nur Memory-IDs. Entschluesselung, Rechtepruefung,
Prompt-Formatierung und `last_accessed_at`/`access_count` bleiben im
`AccountStore`. Neu gespeicherte Account-Memorys werden bei aktivem semantischem
Qdrant-Pfad best-effort in diesen Cache gespiegelt; wenn Qdrant nicht erreichbar
ist, bleibt der verschluesselte AccountStore-Eintrag trotzdem die Wahrheit.
`/reset_memorys` loescht bei aktiver semantischer Qdrant-Suche zuerst den
Qdrant-Cache fuer den Account und danach den lokalen AccountStore; wenn der
Cache nicht geloescht werden kann, wird kein erfolgreicher Reset gemeldet.
`--runtime-status` meldet den Pfad als `memory_index=<Instanz> backend=keyword
status=... semantic=... embedding_provider=... embedding_model=...
embedding_dimensions=...`.
Die Qdrant-Collection-Zeile verwendet fuer Usermemory die aktive semantische
Memory-Konfiguration der Instanz. Wenn mehrere aktive Instanzen verschiedene
Usermemory-Embedding-Modelle oder Dimensionen fuer dieselbe Collection fordern,
meldet der Status `status=config_conflict`. Wenn eine erreichbare Qdrant-
Collection mit falscher Vektorgroesse existiert, meldet der Status
`status=schema_mismatch actual_vector_size=...`; dann muss der rebuildbare
Cache mit konsistenter Modellkonfiguration neu angelegt werden.
`--runtime-status` prueft Qdrant gegen die aktive Qdrant-URL aus
`Bot_Verhalten.md`; wenn aktive Usermemory-/Bibliothekar-Qdrant-Pfade
verschiedene URLs fordern, meldet der Status ebenfalls `config_conflict`.
Qdrant-Suchen filtern Usermemory-Treffer zusaetzlich nach `schema`,
`schema_version`, `embedding_model` und `embedding_dimensions`, damit andere
Payload-Arten, alte Payloads oder Vektorformate nach einem Schema-/Modellwechsel
nicht mit neuen Treffern vermischt werden.
Der rebuildbare Cache wird operatorseitig aus dem AccountStore befuellt. Ohne
Embedding-Flags liest `memory-rebuild` die aktive `Bot_Verhalten.md` der
Instanz und nutzt dieselben `## Memory Search`-Werte wie die Runtime; die Flags
sind nur Overrides fuer Tests oder einen bewussten Modellwechsel:
`collections-ensure` prueft vorhandene Collections zuerst und legt nur fehlende
Collections an; bestehende Collections mit falscher Vektorgroesse werden als
Schemafehler gemeldet, nicht ueberschrieben.
Optionale 384D-/1024D-Nebenindexes nutzen eigene Collections, weil eine
Qdrant-Collection eine feste Vektorgroesse hat.

```bash
teebotus-embedding --instances-dir instances --instance Depressionsbot collections-ensure
teebotus-embedding --instances-dir instances --instance Depressionsbot collections-ensure --include-memory-side-index 384 --include-memory-side-index 1024
teebotus-embedding --instances-dir instances --instance Depressionsbot memory-rebuild --dry-run
teebotus-embedding --instances-dir instances --instance Depressionsbot memory-rebuild --qdrant-url http://127.0.0.1:6333
teebotus-embedding --instances-dir instances --instance Depressionsbot memory-rebuild --qdrant-url http://127.0.0.1:6333 --embedding-provider tei --embedding-model intfloat/multilingual-e5-small --embedding-dimensions 384 --embedding-endpoint http://127.0.0.1:8080/embeddings
teebotus-embedding --instances-dir instances --instance Depressionsbot memory-rebuild --side-index-dimensions 1024 --embedding-provider sentence-transformers --embedding-model BAAI/bge-m3 --embedding-dimensions 1024
python scripts/benchmark_semantic_memory_indexes.py --sizes 1000 10000 100000 --dimensions 64 384 1024 --output-dir ~/Downloads
teebotus-embedding --instances-dir instances --instance Depressionsbot bibliothekar-rebuild --dry-run
teebotus-embedding --instances-dir instances --instance Depressionsbot bibliothekar-rebuild --qdrant-url http://127.0.0.1:6333 --embedding-provider tei --embedding-model BAAI/bge-m3 --embedding-dimensions 1024 --embedding-endpoint http://127.0.0.1:8080/embeddings
```

Alte v2-Qdrant-Cachepunkte konnten noch rohe `account_id` im Payload tragen.
Der normale Runtime-Reset und `memory-rebuild` senden keine rohe Account-ID an
Qdrant. Nur fuer eine bewusste lokale Altlast-Bereinigung gibt es den expliziten
Maintenance-Flag `--include-legacy-raw-account-id-cleanup`; dieser sendet die
betroffene Account-ID zum Loeschen der alten lokalen Qdrant-Payloads, auch wenn
diese noch kein `schema`-Feld hatten.

`TeeBotus.runtime.qdrant_bibliothekar.QdrantBibliothekarIndex` ist der
entsprechende opt-in Sockel fuer Bibliothekar-Chunks. Er indexiert Testchunks
mit Fake-Embeddings in Standardtests, haelt `BAAI/bge-m3` als vorbereiteten
Provider fest und speichert Chunk-Text nur als Hash plus Quellenmetadaten im
Qdrant-Payload. `bibliothekar-rebuild` baut den lokalen Bibliothekar-Store neu
auf und schreibt dessen Chunks in den rebuildbaren Qdrant-Cache; ohne
Embedding-Override nutzt der Operatorpfad einen lokalen Fake-Embeddingvertrag,
damit Dry-Runs und Standardlaeufe keine Providerkosten verursachen.
`LlamaIndexBibliothekarBackend` ist ein optionaler Pilot hinter
`BibliothekarService`: Wenn `llama-index-core` installiert ist, baut er aus den
lokalen Bibliothekar-Chunks einen lokalen In-Memory-Retriever mit LlamaIndex-
`MockEmbedding`; dadurch entstehen keine OpenAI- oder Provider-Kosten. Der
lokale Store bleibt Wahrheit und Rebuild-Quelle. Fake-/Test-Query-Engines
koennen weiterhin zitierfaehige Chunks liefern, ohne den lokalen Store zu
ersetzen. Neben `search`/`retrieve` werden auch typische LlamaIndex-`query`-/
`chat`-Responses mit `source_nodes` akzeptiert. Wenn LlamaIndex nicht verfuegbar
oder die Query-Engine nicht nutzbar ist, bleibt `LocalBibliothekarBackend` der
Fallback; der Runtime-Status meldet dann `backend=llamaindex
status=unavailable`. Bei erfolgreichem lokalen Pilot meldet er
`backend=llamaindex status=ready store=llamaindex target=local_in_memory`.
`TeeBotus.runtime.source_quality.SourceQualityPipeline` ist ein lokaler
Vor-Index-Gate fuer Quellen: Dateityp/Groesse/Metadaten werden deterministisch
geprueft, ein optionaler NLI-Verifier kann Claims gegen Evidenz klassifizieren,
und das Resultat routet nach `accepted`, `quarantine` oder `rejected`. Es ist
kein einzelnes LLM als Wahrheitsrichter und greift noch nicht automatisch in den
Standard-Bibliothekar ein.
`TeeBotus.bibliothekar.source_harvester.SourceHarvester` nutzt dieses Gate fuer
lokale Dateien: Quellen landen mit SHA-256-Dedupe und Manifest zuerst unter
`accepted/`, `quarantine/` oder `rejected/`; diese Staging-Verzeichnisse werden
vom lokalen Bibliothekar-Index ausgeschlossen. Akzeptierte Dateien sind nur als
`accepted_for_ingest` markiert und werden erst durch den expliziten Promote-
Schritt nach `books/` in die indexierbare Hauptbibliothek uebernommen.

Pydantic-AI/LangGraph optional. Pydantic-Schemas werden nur fuer strukturierte Subtasks genutzt, darunter `IntentDecision`, `MemoryCandidate`, `ReminderDecision`, `BibliothekarQueryDecision`, `ToolSafetyDecision`, `SourceQualityDecision`, `AgentTaskDecision` und `ProactiveToolCallDecision`; Slash-Commands bleiben klassische Parser.
`TeeBotus.decisions` exportiert dieselben Schemas als Plan3-Fassade und liefert
mit `FakeDecisionModel` einen providerfreien Test-Runner fuer strukturierte
Entscheidungen. Die thematischen Module `TeeBotus.decisions.intent`,
`memory`, `reminder`, `bibliothekar`, `source_quality`, `tool_safety`,
`agent_task`, `proactive`, `youtube` und `pydantic_agent` bilden die stabile
Importgrenze fuer neue Plan3-Subtasks; `ai_structures` bleibt die interne
Schema-Implementierung.
Der Standard-Builder fuer echte strukturierte Entscheidungen ist
`build_router_pydantic_ai_model_runner("structured_decision")`; er speichert die
aufgeloeste Route als Runner-Metadaten (`llm_purpose`, `llm_provider`,
`model_name`) und vermeidet, dass Subtasks eigene Modellnamen am Router vorbei
verdrahten. Wenn diese Route auf `hf_pool` zeigt, wird der Pool-Selector
`pool:default#structured_decision` fuer echte Pydantic-AI-Laeufe zu einem
OpenAI-kompatiblen HF-Router/Endpoint-Modell aufgeloest; bei fehlender oder
deaktivierter HF-Konfiguration wird der konfigurierte lokale Fallback
`local_ollama` als Pydantic-AI-Ollama-Modell genutzt, sofern die Route ihn
enthaelt. Ohne Fallback bleibt das ein klarer `hf_pool unavailable`-Status vor
dem ersten Live-Call.
Der Runtime-Runner folgt standardmaessig dem Text-LLM-Schalter. Pro Instanz
kann er in `Bot_Verhalten.md` ueber `## LLM` gesteuert werden:

```markdown
## LLM
- structured_decision_enabled: ja
```

Echte Pydantic-AI-Provider bleiben optional.

```bash
python3 -m pip install '.[agents]'
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_structured_decision_hf.py
```

Qdrant soll lokal auf `127.0.0.1` gebunden bleiben. `qdrant_url` darf nur auf `127.0.0.1`, `localhost` oder `::1` mit gueltigem Port zeigen und keine Zugangsdaten, Pfade, Query-Parameter oder Fragmente enthalten; nicht-lokale Ziele werden im Status als ungueltig gemeldet. Wenn Haystack/Qdrant konfiguriert, aber zur Laufzeit nicht verfuegbar ist, faellt die Suche auf den lokalen Bibliothekar zurueck, statt normale Botantworten zu crashen.

`python3 -m TeeBotus --runtime-status --channels telegram` prueft bei `backend: haystack` die optionalen Haystack/Qdrant-Abhaengigkeiten und die Qdrant-Erreichbarkeit. Bei erreichbarem Backend meldet der Status `store=qdrant target=http://127.0.0.1:6333 status=reachable` plus Dokument-/Chunk-Zahlen aus dem rebuildbaren lokalen Index; bei fehlendem oder nicht erreichbarem Backend meldet er `status=unavailable` oder `status=unreachable` mit Fehlertext.

LangGraph ist nicht der Botkern. Der erste Pilot liegt unter
`TeeBotus/runtime/graphs/` und betrifft `Bibliothekar Deep Query`; der Ablauf
ist `classify -> retrieve -> rerank -> answer -> citation_check -> fallback`.
Zusaetzlich gibt es einen `SourceHarvester`-Workflow fuer
`discover -> score -> finalize`, der Quellen nur nach Quality-Gate als
`ready_for_ingest`, `review_required`, `duplicate`, `rejected` oder `failed`
markiert. Ohne installiertes `langgraph` laeuft derselbe serialisierbare State
linear weiter. Normale Chatantworten, `/status`, `/help`, `/ping` und einfache
Textregeln laufen nicht durch LangGraph.
CrewAI ist ebenfalls nicht Standard. `TeeBotus.runtime.crew_pilots` beschreibt
nur geplante Spezialexpeditionen fuer Bibliothekar, SourceQuality und Anki;
`--runtime-status` zeigt diese als `crew_pilot=... status=planned` mit
Dependency-Status, ohne normale Antworten umzurouten.

Deep-Query-Pilot:

```bash
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot query "Therapie Schlaf" --deep --top-k 3
```

## MCP/FastMCP Pilot

MCP/FastMCP ist nur als streng begrenzte Tool-Schicht vorgesehen. Der erste Pilot liegt unter `TeeBotus/mcp_tools/` und registriert ausschliesslich allowlistete read-only Tools:

- `bibliothekar.search`: sucht in der Instanz-Bibliothek.
- `memory.search`: sucht im verschluesselten Account-Memory des aktuellen Accounts.

Nicht registriert sind freie Shell, beliebige Dateipfade, `.env`-Zugriff, Secret-Ausgabe, ungeprueftes Loeschen, Portscans oder Codex-Ausfuehrung. Bekannte spaetere Tools wie `youtube.transcribe`, `export.account` oder `codex.exec` sind als Policies sichtbar, bleiben aber standardmaessig deaktiviert und werden erst mit separater Implementierung, Policy- und Bestaetigungsstufe registriert.
`memory.search` wird nur in einem explizit privaten Chat-Kontext registriert; Gruppen- oder unklarer Kontext bekommen auch bei vorhandenen Account-Daten keinen Memory-Toolzugriff.
`bibliothekar.search` akzeptiert neben `query`, `top_k`, `max_prompt_chars` und `max_quote_chars` auch die oeffentlichen Bibliotheksfilter `category`, `topic`/`keyword`, `file`/`relative_path`, `extension` und `suffix`. Private Account-, Identity- oder Instanzfilter werden nicht an die Bibliothekssuche durchgereicht.

Konfiguration in `Bot_Verhalten.md` ist flach und allowlistet:

```text
## MCP Tools
- bibliothekar.search.enabled: true
- bibliothekar.search.read_only: true
- memory.search.enabled: true
- memory.search.read_only: true
- memory.search.private_chat_only: true
```

FastMCP ist optional. Ohne installiertes `fastmcp` bleibt TeeBotus importierbar; der Adapter meldet dann nur, dass das Extra `[tools]` fehlt. Installation:

```bash
python3 -m pip install '.[tools]'
```

Plan2-Extras sind absichtlich gepinnt. Fuer eine saubere Resolver-Schiene ist Python 3.13 die empfohlene Runtime; Python 3.14 bleibt im Dependency-Doctor advisory. `[llm]` pinnt `litellm==1.89.2`, `[tools]` haelt `python-dotenv==1.2.2`, `fastmcp==3.4.2` und `watchdog==6.0.0` aktuell. Installiere `[llm]` und `[tools]` dort nicht in einem einzigen Pip-Resolver-Vorgang, sondern sequenziell ueber `scripts/install_adapter_deps.py` oder getrennte `pip install`-Aufrufe. TeeBotus prueft diese Pins in `scripts/check_adapter_deps.py` und `scripts/check_plan2_optional_extras.py`.

OpenAI-Flex-Processing wird ueber `service_tier: flex` im `## OpenAI`-Block der aktiven Instanz-`Bot_Verhalten.md` aktiviert. Gemini/Vertex-Flex laeuft getrennt ueber `service_tier: flex` im `## LLM`-Block oder die oben genannten `TEEBOTUS_GEMINI_*`-/`TEEBOTUS_LLM_SERVICE_TIER*`-Schalter. Wegen der laengeren Laufzeit von Flex-Anfragen ist dort auch `timeout_seconds: 900` gesetzt.

Websuche wird ueber `web_search: true` aktiviert. Mit `web_search_context_size: medium` bekommt das Modell einen mittleren Suchkontext. `web_search_required: false` laesst `tool_choice` auf `auto`, damit das Modell nur sucht, wenn es fuer die Antwort sinnvoll ist.

`rule_file: Bot_Rüstzeug.md` bindet eine zusaetzliche Markdown-Datei neben der aktiven Instanz-`Bot_Verhalten.md` als Grundregelwerk fuer jede OpenAI-Unterhaltung ein. Der Bot laedt diese Datei zusammen mit `Bot_Verhalten.md` neu, sobald eine der beiden Dateien geaendert wurde.

## User-Memory

Der Account-Layer speichert accountbezogene Daten unter `instances/<instance>/data/accounts/accounts/<account_id>/`.

Strukturierte Accountdaten werden verschluesselt gespeichert. Interne operatorgepflegte Hinweise sind eine separate Vertrauensebene und werden Usern nicht mit Dateinamen offengelegt.

Die strukturierten AccountStore-Schluessel liegen instanzgebunden im Desktop Secret Service via `secret-tool`. Das alte senderbezogene `User_Memory_Key.bin`-Backend wird nicht mehr genutzt.

Wenn ein optionaler strukturierter Runner aktiv ist, kann der normale Antwortpfad vor dem Speichern eine `MemoryCandidate`-Entscheidung einholen. Automatisch gespeichert werden nur ausreichend sichere Kandidaten mit `confidence >= 0.7` und `sensitivity` unter `high`; `should_store=false`, `memory_type=none` oder `sensitivity=high` verhindern das automatische Schreiben.

Der Speicher ist accountbezogen und nicht mehr an `data/users/<telegram_sender_id>` gebunden. `instances/*/data/` ist per `.gitignore` ausgeschlossen.

Mehr zur Datenhaltung, zum Schluesselmodell und zu den Grenzen der Verschluesselung steht in [docs/privacy-and-encryption.md](docs/privacy-and-encryption.md). Deutsche und englische Fassungen liegen zusaetzlich unter [docs/privacy-and-encryption.de.md](docs/privacy-and-encryption.de.md) und [docs/privacy-and-encryption.en.md](docs/privacy-and-encryption.en.md).

Kurzantwort fuer Datenschutzfragen:

- Strukturierter Nutzer-Memory wird accountbezogen at rest verschluesselt.
- Interne operatorgepflegte Hinweise sind eine separate Vertrauensebene und werden nicht mit internen Dateinamen offengelegt.
- Der zugehoerige Key liegt instanzgebunden im Desktop Secret Service.
- Ein Admin ohne passenden Key sieht in den verschluesselten Index-/Entry-Dateien keine Klartextdaten.
- Das laufende Bot-Prozessmodell kann Daten zum Antworten trotzdem entschluesseln.
- Wer die Laufzeit, den Speicher oder den passenden Key kontrolliert, kann weiterhin auf Klartext stossen.

Wenn du die Standardantwort brauchst, steht sie in [docs/privacy-and-encryption.md](docs/privacy-and-encryption.md) als kopierfertiges Template.

Bei einem produktiven Versionswechsel benachrichtigt der Telegram-Start alle Telegram-Identities, die in den letzten sieben Tagen in der jeweiligen Instanz aktiv waren. Pro Version und Identity wird nur einmal gesendet; die Nachricht nennt nur die neue Version, einen kurzen neutralen Hinweis und einen kleinen lokal aus Memory-Signalen abgeleiteten Witz.

Wenn ein User `/reset_memorys` sendet oder den Bot frei formuliert auffordert, seine Erinnerungen zu loeschen, fragt der Bot zuerst nach Bestaetigung. Erst nach einer klaren Antwort wie `ja` wird ausschliesslich das User-Memory des aktuellen Accounts auf den initialen Skeletonzustand zurueckgesetzt: Index leer, JSONL leer. Admingepflegte interne Zusatzhinweise bleiben dabei unveraendert. Fremde User-Memorys und das Instanz-Arbeitsgedaechtnis werden nie durch User geloescht. Falls ein User danach fragt, weist der Bot darauf hin, dass das Instanz-/Arbeitsgedaechtnis keine userbezogenen Daten enthaelt.

## Instanz-Arbeitsgedaechtnis

Jede Instanz hat zusaetzlich ein gemeinsames Arbeitsgedaechtnis im eigenen `data`-Ordner:

- `instances/Bote_der_Wahrheit/data/Working_Memorys.json`
- `instances/Bote_der_Wahrheit/data/Working_Memorys.entries.jsonl`
- `instances/Depressionsbot/data/Working_Memorys.json`
- `instances/Depressionsbot/data/Working_Memorys.entries.jsonl`

Dieses Arbeitsgedaechtnis gilt fuer alle User derselben Instanz und darf deshalb keine User-IDs, Namen, Usernames, Chat-IDs, Chat-Titel, Rohzitate aus Usernachrichten oder eindeutig userbezogene Fakten enthalten.

Der Bot legt die Dateien beim Start automatisch an und nutzt vorhandene, ausgewaehlte Eintraege als eigene `Instanz-Arbeitsgedaechtnis`-Sektion im Text-LLM-Kontext. Aktuell wird dieses globale Arbeitsgedaechtnis nicht automatisch aus Chats befuellt, weil die genaue Logik noch kuratiert werden muss. Manuell ergaenzte Eintraege werden im JSONL-Log gespeichert; der Index enthaelt Keywords, Recent-Liste und Byte-Positionen fuer gezieltes Lesen.

## Alle Bots starten

Alle lokal vorhandenen Instanzen mit konfigurierten Tokens startest du mit:

```bash
python3 -m TeeBotus --all
```

Der Bot sucht dabei nach `instances/*/Bot_Verhalten.md`. Instanzen ohne Telegram-Token werden uebersprungen; bei fehlerhaften OpenAI-Key-Slots bricht der Start mit einer Meldung ab.

Live-Validierung:

```bash
cd TeeBotus
python3 scripts/validate_flex.py
```

## Nachrichten loeschen

Der Bot merkt sich die `message_id` seiner eigenen Antworten im Arbeitsspeicher. Damit funktionieren:

- `/cleanup N` loescht die letzten N zuletzt gemerkten Nachrichten im aktuellen Chat.
- `/cleanup all` loescht alle zuletzt gemerkten Nachrichten im aktuellen Chat.

Nach einem Bot-Neustart ist diese interne Liste leer. In Gruppen muss der Bot Admin sein und die Berechtigung zum Loeschen von Nachrichten haben, sonst kann Telegram `deleteMessage` ablehnen.

## Netzwerkfehler

Telegram-Long-Polling-Verbindungen koennen gelegentlich durch Telegram, Provider oder lokale Netzwechsel beendet werden, zum Beispiel mit `Connection reset by peer`. Der Bot behandelt solche Fehler als temporaer, wartet mit Backoff und verbindet sich erneut.

## Tests

```bash
cd TeeBotus
python3 -m pytest -q
python3 -m compileall -q TeeBotus scripts
python3 scripts/check_adapter_deps.py
python3 -m pytest -q tests/test_benchmarks_*.py tests/test_graphs_*.py
```

## Anpassen

Normale Anpassungen gehen ueber die jeweilige Instanz-`Bot_Verhalten.md`. Code-Aenderungen brauchst du erst, wenn der Bot neue Faehigkeiten bekommen soll, zum Beispiel Datenbanken, HTTP-Abfragen oder Admin-Rechte.
