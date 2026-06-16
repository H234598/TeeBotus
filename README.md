# TeeBotus

TeeBotus ist ein kleiner Python-Bot mit Telegram-Long-Polling als stabilem Einstieg und optionalen Extras fuer Signal, Matrix, lokale Transkription, LLM-Provider, RAG/Bibliothekar und Agenten-Workflows. Er kann mehrere Instanzen mit getrennten Einstellungen starten.

## Funktionen

- `/start` begruesst neue Nutzer
- `/help` zeigt die verfuegbaren Befehle
- `/ping` antwortet mit `pong`
- `/status` zeigt Laufstatus, TeeBotus-Version, GitHub-Commithistorie, Memory-Groesse und Userfile-Verschluesselung des anfragenden Nutzers
- `/history` zeigt GitHub-Repo, Commits und lokale Release-Tags. Fragen wie `Was ist neu?`, `Programmhistorie`, `Commits`, `Changelog` oder `Programmänderungen` nutzen denselben Offline-Pfad.
- `/chatid` zeigt die aktuelle Chat-ID
- `/reset` loescht den OpenAI-Verlauf fuer den aktuellen Chat
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

Alternativ geht der All-Start auch per Environment:

```bash
TELEGRAM_BOT_INSTANCE=all python3 -m TeeBotus
```

Fuer parallel laufende Bots braucht jede Telegram-Bot-Identitaet einen eigenen BotFather-Token.

Der Bot laeuft dann im Terminal. Mit `Ctrl+C` beendest du ihn.

Der Bot loggt nach `stdout`, wenn Telegram-Nachrichten eingehen oder Bot-Nachrichten ausgehen. Geloggt werden nur Metadaten wie Chat-ID, Message-ID, Nachrichtentyp und Laenge, nicht der Nachrichteninhalt.

`ALL_BOTS_DEFAULT.md` enthaelt unter `## Laufzeitkonfiguration` echte Default-Schalter fuer den Start. Werte aus Shell, systemd, Docker oder `.env` haben Vorrang; die Default-Datei fuellt nur fehlende Environment-Werte.

## Plan3 Account-Runtime

`TeeBotus/bot.py` bleibt der stabile Entry-Point. Telegram laeuft weiter ueber `TeeBotus/adapters/telegram_runtime.py`; konfigurierte Signal- und Matrix-Slots koennen zusaetzlich ueber die Plan3-Runtime gestartet werden.

Die Runtime-Konfiguration kannst du separat pruefen:

```bash
python3 -m TeeBotus --runtime-status --channels telegram
```

`--channels telegram` startet nur Telegram. `--channels signal` startet nur konfigurierte Signal-Slots. `--channels matrix` startet nur konfigurierte Matrix-Slots. Kombinationen mit Telegram starten die zusaetzlichen Slots im Hintergrund und danach den stabilen Telegram-Poller.

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

Der erzeugte Timer ruft standardmaessig `teebotus-proactive --dispatch --plan --tool-plan` auf. Das fuehrt lokale Reflection-Planung, Due-Selection und Versand ueber die konfigurierten Proactive-Backends aus. LLM-Planung ist mit `--llm-plan` verfuegbar; die native Tool-Agent-Planung mit lokal validierten Memory-/Outbox-Toolcalls ist mit `--tool-plan` im systemd-Renderer der Default. Toolcalls laufen zusaetzlich durch `ProactiveToolCallDecision`, damit bekannte Tools nur mit Pflichtargumenten und erlaubten Argumenten in die Plananwendung kommen. Beide Pfade bleiben hinter `TEEBOTUS_PROACTIVE_LLM_PLANNER_INSTANCES` beziehungsweise Instanz-Flag und passendem OpenAI-Key aktiv. Fuer den Proactive-Key wird bevorzugt `OPENAI_API_KEY_<INSTANCE>_PROACTIVE` genutzt, danach die instanzweiten OpenAI-Key-Fallbacks.

Usergewuenschte Erinnerungen laufen ebenfalls ueber die Proactive-Outbox. Klassische Formulierungen werden lokal erkannt; bei optionaler strukturierter `ReminderDecision` kann `recurrence` als `daily`, `weekly`, `monthly` oder `every N minutes/hours/days/weeks` gespeichert werden. Nach erfolgreichem Versand wird ein wiederkehrendes Reminder-Item mit naechstem `due_at` erneut gequeued.

Signal braucht das Python-Paket `signalbot`, die native `signal-cli-rest-api` und `signal-cli`. Die festen Versionen stehen in `adapter-dependencies.lock`; die komplette gepinnte Adapter-Schicht kann reproduzierbar installiert und danach geprueft werden mit:

```bash
python3 scripts/install_adapter_deps.py
python3 scripts/check_adapter_deps.py
```

`nio-bot 1.0.2.post1` deklariert upstream noch `matrix-nio==0.20.*`. TeeBotus prueft aktuell den echten Runtime-Override `matrix-nio==0.25.0` mit `h11==0.16.0`, weil unsere genutzten `nio-bot`-/`matrix-nio`-Vertraege damit laufen und die moderne `httpcore`-/`httpx`-Kette importierbar bleibt. `scripts/install_adapter_deps.py` installiert `nio-bot` deshalb gezielt ohne dessen alte `matrix-nio`-Abhaengigkeit, installiert `signal-cli` nach `~/.local/opt` mit Symlink in `~/.local/bin`, baut `signal-cli-rest-api` aus dem gepinnten Upstream-Tag mit Go nach `~/.local/opt` und laesst danach `scripts/check_adapter_deps.py` laufen.

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

Der uebergreifende Quick-Benchmark fuer Plan2-Kernpfade schreibt Markdown und JSON. Standardmaessig nutzt er keine echten Provider-Calls, keine Netzsendung und keine API-Kosten:

```bash
python3 scripts/run_benchmarks.py --quick --output /home/teladi/Downloads/teebotus-benchmarks-latest.md --json-output /home/teladi/Downloads/teebotus-benchmarks-latest.json
```

Abgedeckt werden Account-Memory, Bibliothekar lokal plus Haystack/Qdrant-Backendpfad mit Fake-DocumentStore, LLM-Router, Proactive-Agent, Messenger-Adapter-Contracts, YouTube-/Transkriptionsparser, Status/Doctor, Datenbank-Fallback-Policy und LangGraph-Flows. PostgreSQL wird im Quick-Modus als `skipped` markiert, solange kein expliziter DSN uebergeben wird. Fuer Regressionen kann ein frueherer JSON-Lauf als Baseline verglichen werden:

```bash
python3 scripts/run_benchmarks.py --quick --baseline-json /home/teladi/Downloads/teebotus-benchmarks-latest.json --output /home/teladi/Downloads/teebotus-benchmarks-compare.md --json-output /home/teladi/Downloads/teebotus-benchmarks-compare.json
```

Plan2-Akzeptanztests:

```bash
python3 scripts/check_plan2_acceptance.py
```

Der Runner startet keine Bot-Loops und ruft bewusst nicht `python3 -m TeeBotus --all` auf. Er prueft Version, Runtime-Status, die Plan2-Testgruppen, Bibliothekar-Fixtures, Quick-Benchmarks und Adapter-Abhaengigkeiten. Zum reinen Anzeigen der Kommandos:

```bash
python3 scripts/check_plan2_acceptance.py --list
python3 scripts/check_plan2_acceptance.py --dry-run
```

Optionale Live-/Security-Probes bleiben bewusst explizit und nicht blockierend:

```bash
python3 scripts/check_plan2_acceptance.py --list --include-qdrant-live --include-audit
```

Wenn eine alte Klartext-Sicherung vorhanden ist, kann der Runner zusaetzlich nur lesende Recovery-Reports und einen Legacy-Import-Dry-run nach `/home/teladi/Downloads` schreiben:

```bash
python3 scripts/check_plan2_acceptance.py --skip-runtime-status --legacy-instances-dir /home/teladi/TeeBotus.bak2
```

Der Legacy-Pfad darf auf einen Backup-Root oder direkt auf einen konkreten `instances*`-Unterordner wie `/home/teladi/TeeBotus.bak2/instances.bak` zeigen. Der Recovery-Reporter und Importer waehlen bei Backup-Roots automatisch den besten passenden `instances*`-Unterordner mit Plaintext-User-Memorys.

Hinweis zur Plan2-Testhistorie: Die frueher im Plan genannten LLM-Dateien
`tests/test_llm_base.py` und `tests/test_openai_provider.py` sind in der
aktuellen Teststruktur aufgeteilt. `tests/test_llm_client.py` deckt die
providerneutralen LLM-Client-/Capability-Primitiven plus LiteLLM-Textadapter ab,
`tests/test_llm_package.py` deckt die oeffentlichen LLM-Paketexports und den
`OpenAIProvider`-Wrapper ab. Der Acceptance-Runner nimmt die aktuellen
`tests/test_*.py`-Module als Quelle der Wahrheit und fuehrt diese komplette
Plan2-Testflaeche aus.

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

Wenn `/status` oder `--runtime-status` nicht entschluesselbare Account-Memory-Payloads meldet, kann vor jeder Reparatur ein read-only Recovery-Report erzeugt werden:

```bash
python3 -m TeeBotus.admin memory-recovery --instances-dir instances
python3 -m TeeBotus.admin memory-recovery --instances-dir instances --format json --output /home/teladi/Downloads/teebotus-memory-recovery.json
```

Der Recovery-Report vergleicht SQLite-Primary, SQLite-Fallback und vorhandene JSON-Dateien pro Account. Er gibt nur Zaehler, Dateipfade und Fehlerklassen aus, keine Secrets und keine rohen Memory-Payloads. Wenn kein Source als `recoverable=True` markiert ist, darf der Bot keine automatische Datenmigration oder Loeschung versuchen; dann fehlt der passende alte Schluessel oder eine lesbare Sicherung.

Wenn eine alte Plaintext-Sicherung mit `instances/<Instanz>/data/users/<telegram_id>/User_Memory_Entries.jsonl` existiert, kann der Recovery-Report diese Quelle zusaetzlich nur zaehlen:

```bash
python3 -m TeeBotus.admin memory-recovery --instances-dir instances --legacy-instances-dir /home/teladi/TeeBotus.bak2
```

Der eigentliche Import ist ein separater, standardmaessig nicht-destruktiver Dry-Run:

```bash
python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /home/teladi/TeeBotus.bak2 --target-instances-dir instances --replace-unreadable-account-metadata
```

Fuer eine pruefbare Preflight-Akte koennen Markdown und JSON geschrieben werden:

```bash
python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /home/teladi/TeeBotus.bak2 --target-instances-dir instances --replace-unreadable-account-metadata --json-output /home/teladi/Downloads/teebotus-legacy-import-preflight.json --markdown-output /home/teladi/Downloads/teebotus-legacy-import-preflight.md
```

Der Preflight-Bericht enthaelt `apply_safety`. Vor einem echten Import muss `apply_allowed_now=true`, `apply_requires_stopped_bot=false` und `running_bot_process_count=0` gelten. Wenn dort laufende Prozesse aufgefuehrt sind, zuerst Bot und Proactive-Jobs stoppen und den Preflight erneut schreiben.

Ein echter Import braucht `--apply`. Wenn aktuelle Account-Metadaten nicht entschluesselbar sind, sichert `--replace-unreadable-account-metadata --apply` den aktiven Account-Store komplett weg: `Account_Index.json`, `Account_Identities.json`, `Account_Secrets.json`, `accounts/`, `Account_Memory.sqlite3`, Fallback-SQLite sowie WAL/SHM. Danach werden neue Account-Mappings aus `telegram:user:<id>` erzeugt und die Legacy-Eintraege verschluesselt in den aktuellen AccountStore geschrieben. Vor diesem Schritt muss der Bot gestoppt sein; das Script verweigert `--apply` standardmaessig, wenn `python -m TeeBotus` oder `teebotus-proactive` noch laufen. Danach `python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix` ausfuehren.

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

Vorbereitete Profile decken lokale und Remote-Provider ab, unter anderem Ollama, Hugging Face, Groq, Gemini und OpenAI-kompatible LiteLLM-Modelle. Remote-Fallbacks sind standardmaessig aus. Ein Fallback auf ein Remote-Profil wird nur genutzt, wenn der jeweilige Codepfad explizit `allow_remote_fallback=True` setzt.

Zur Laufzeit kann ein konkretes Profil ueber `profile: ...` in `Bot_Verhalten.md` oder ueber `TEEBOTUS_LLM_PROFILE_<INSTANZ>` und kanalspezifische Varianten gesetzt werden. Telegram, Signal und Matrix bauen ihren Text-LLM-Client dann aus diesem Profil; ohne Profil bleibt das bisherige direkte Provider-/OpenAI-Verhalten erhalten.

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
```

Environment-Fallbacks heissen `TEEBOTUS_LLM_ENABLED`, `TEEBOTUS_LLM_PROVIDER`, `TEEBOTUS_LLM_MODEL`, `TEEBOTUS_LLM_PROFILE`, `TEEBOTUS_LLM_PURPOSE`, `TEEBOTUS_LLM_ALLOW_REMOTE_FALLBACK`, `TEEBOTUS_LLM_BASE_URL`, `TEEBOTUS_LLM_API_KEY`, `TEEBOTUS_LLM_TIMEOUT_SECONDS`, `TEEBOTUS_LLM_MAX_OUTPUT_TOKENS` und `TEEBOTUS_LLM_TEMPERATURE`; instanz-, kanal- und slot-spezifische Varianten werden ebenfalls aufgeloest. Alte `openai_*`-Felder bleiben kompatibel.

`TEEBOTUS_LLM_PURPOSE` wird tolerant normalisiert: Gross-/Kleinschreibung ist egal, Leerzeichen und Bindestriche werden zu Unterstrichen. `Structured Decision`, `structured-decision` und `structured_decision` routen also auf denselben Eintrag in `config/llm_routing.yaml`.

Ollama Quickstart:

```bash
ollama serve
ollama pull llama3.1:8b
TEEBOTUS_LLM_PROVIDER=litellm \
TEEBOTUS_LLM_MODEL=ollama_chat/llama3.1:8b \
TEEBOTUS_LLM_BASE_URL=http://127.0.0.1:11434 \
python3 -m TeeBotus --runtime-status --channels telegram
```

`--runtime-status` prueft lokale Ollama-Targets ueber `127.0.0.1:11434` und meldet gefundene Modelle. Ollama ist der bevorzugte lokale Textprovider; Voice, Bilder und OpenAI-spezifische Tool-Calls bleiben beim OpenAI-Client, solange dafuer kein lokales Pendant angebunden ist.

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

Sobald dieser User mit diesem Bot bekannt ist, darf der User ihn beliebig nennen. Die Zuordnung laeuft dann ueber die Telegram-Sender-ID und den User-Memory.

Feste Slash-Befehle werden nicht an OpenAI gesendet.

`/Call_a_Teladi` ist ein fester Notfallbefehl. Der Bot fragt nach, welche Emergency Message weitergeleitet werden soll, sendet einen kurzen Herkunfts-Header an Teladi und kopiert danach die naechste Telegram-Nachricht unveraendert dorthin. Pro Telegram-Sender-ID kann der Befehl nur einmal innerhalb von 24 Stunden ausgeloest werden; weitere Versuche werden mit Restzeit abgelehnt. Der Cooldown wird im lokalen Instanz-`data`-Ordner gespeichert und uebersteht Bot-Neustarts. Der interne Zielchat wird Usern nicht angezeigt.

Lange OpenAI-Antworten werden automatisch in mehrere Telegram-Nachrichten aufgeteilt, damit Telegrams Nachrichtenlimit nicht erreicht wird.

Sprachnachrichten werden mit `/voice Text` erzeugt. Alternativ kannst du auf eine Textnachricht antworten und nur `/voice` senden; der Bot vertont dann den Text der beantworteten Nachricht. Die Default-Stimme wird in der aktiven Instanz-`Bot_Verhalten.md` ueber `voice_model`, `voice`, `voice_format`, `voice_speed` und `voice_instructions` gesteuert. Nutzer koennen mit `/voicemodel <stimme>` eine eigene OpenAI-Stimme waehlen, zum Beispiel `/voicemodel onyx`; `/voicemodel reset` nutzt wieder den Instanz-Default. Mit `/mimic_voice on` kann ein aus eigenen Sprachnachrichten abgeleitetes Sprechweisen-Profil fuer TTS genutzt werden; `/mimic_voice before` setzt diese Anweisung vor den Dialekt, `/mimic_voice after` danach, `/mimic_voice reset` loescht das Profil. Die aktuelle OpenAI-Voice-Liste steht unter https://platform.openai.com/docs/guides/text-to-speech#voice-options. Standard ist `voice_format: opus`, passend fuer Telegram-Sprachnachrichten.

`/codex Prompt` startet den lokalen Codex-CLI-Prozess aus dem Bot-Prozess heraus. Zugelassen sind nur die in der aktiven Instanz-`Bot_Verhalten.md` unter `## Codex` eingetragenen Telegram-Sender-IDs. Der Bot arbeitet dabei aus dem Repository-Root und benutzt kein `shell=True`.

Automatische Sprachnachrichten werden in der aktiven Instanz-`Bot_Verhalten.md` ueber `auto_voice_enabled`, `auto_voice_every`, `auto_voice_max_words` und `auto_voice_skip_sources` gesteuert. Aktuell wird jede dritte OpenAI-Antwort unter 50 Woertern ohne Quellen als Sprachnachricht gesendet.

Eingehende Sprachnachrichten werden transkribiert und danach durch dieselbe Textlogik geschickt wie normale Nachrichten. Gesteuert wird das in der aktiven Instanz-`Bot_Verhalten.md` ueber `transcription_enabled`, `transcription_backend`, `local_transcription_model`, `transcription_model`, `transcription_fallback_model`, `transcription_language`, `transcription_prompt`, `transcription_error` und `transcription_empty`. Mit `transcription_backend: local` nutzt der Bot lokal `faster-whisper` oder die `whisper` CLI und faellt nicht auf OpenAI zurueck. Mit `transcription_backend: openai` nutzt er die OpenAI-Transkription; nur in diesem Modus versucht er bei leerem Ergebnis einmal `transcription_fallback_model`, wenn dieses Feld gesetzt und vom Primaermodell verschieden ist. Der transkribierte Inhalt wird nicht in die stdout-Logs geschrieben. Audio-Dateien werden nicht gespeichert; im User-Memory landet nur das Transkript als Text.

YouTube-Transkripte laufen zweistufig: Zuerst versucht der Bot mit `yt-dlp` vorhandene YouTube-Untertitel zu laden. Wenn keine Untertitel gefunden werden, fragt er vor lokaler Transkription nach Live-Ausgabe und LLM-Weitergabe. Lokale Transkription laeuft ueber `faster-whisper` mit Modell `tiny`, automatischer Sprachwahl fuer Deutsch/Englisch, maximal zwei CPU-Threads, `nice -n 19` und, falls vorhanden, `ionice -c 3`. Der lokale Transkriptionsjob laeuft in einem Hintergrund-Worker; Telegram-Polling bleibt aktiv. Timeout ist `7200` Sekunden. Nach 5, 15, 60 und 90 Minuten prueft ein Watchdog, ob der Child-Prozess noch plausibel lebt. Wenn nicht, beendet der Bot die Prozessgruppe und meldet den Fehler im Chat. Reine Python-`resource_tracker`-Warnungen beim Abbruch werden aus dem Telegram-Fehlertext herausgefiltert.

Wenn der Freitext-Parser Live-Ausgabe oder LLM-Weitergabe nicht vollstaendig erkennt und `youtube_option_llm_fallback: ja` gesetzt ist, kann ein vorhandener OpenAI-/LLM-Client die beiden Optionen eng als JSON klassifizieren. Parser-Ergebnisse gewinnen dabei; das LLM fuellt nur fehlende Werte. Solche nachtraeglich erkannten Formulierungen werden URL-redaktiert in `instances/{instance}/data/YouTube_Parser_Misses.jsonl` protokolliert und instanzlokal wieder vom Parser gelesen, damit dieselbe Formulierung beim naechsten Mal ohne LLM-Fallback erkannt wird. Der Wiedererkennungsabgleich ist konservativ tokenbasiert und ignoriert URL- und Befehlsfuelltext, verlangt aber mehrere spezifische Tokens.

Die zaehlbaren Grundformen des Live/LLM-Parsers koennen mit `python3 scripts/youtube_parser_stats.py` oder maschinenlesbar mit `python3 scripts/youtube_parser_stats.py --json` neu berechnet werden. Die konkrete Sprache bleibt wegen freier Regex-Zwischenraeume und Learned-Phrases offen; das Skript weist deshalb eine konservative zaehlbare Untergrenze aus. Ein LLM-Fallback zur Klassifikation unklarer Live/LLM-Optionen ist aus Kostengruenden standardmaessig aus und muss in `Bot_Verhalten.md` explizit mit `youtube_option_llm_fallback: ja` aktiviert werden.

Der aktuelle Bestand gelernter Parser-Misses kann mit `python3 scripts/youtube_parser_misses_report.py --instances-dir instances` ausgewertet werden. Der Report gruppiert Formulierungen, zeigt ob der Basisparser sie inzwischen direkt erkennt, markiert verbleibende Kandidaten fuer dauerhafte Parser-Regeln und gibt pro Kandidat eine kompakte Promotion-Suggestion mit Zielwerten und spezifischen Tokens aus. Mit `--regression-json` erzeugt der Report eine kompakte Testfall-Liste; mit `--pytest-snippet` erzeugt er direkt einen einfuegbaren `pytest.mark.parametrize`-Block fuer Parser-Regressionen.

## Bibliothekar, Haystack und LangGraph

Der Bibliothekar ist die lokale Instanz-Bibliothek unter `instances/<instance>/data/Bibliothek`. Dort koennen `.pdf`, `.epub`, `.docx`, `.txt`, `.md` und `.markdown` abgelegt werden. Der lokale Store baut daraus `.bibliothekar/index.json` und `.bibliothekar/chunks.jsonl`. Antworten duerfen kurze Abschnitte daraus zitieren und muessen dann Titel, Datei, Locator und `chunk_id` nennen.

Das Bibliothekar-Indexschema speichert pro Dokument und Chunk stabile Quellenmetadaten wie `source_id`, `file_sha256`, `file_type`, `language`, `chunk_index`, `ingested_at` und `embedding_model`; aeltere Cache-Schemas werden beim Zugriff automatisch neu aufgebaut.

Wichtig: Account-Memory wird nicht in Haystack/Qdrant indexiert. Account-Memory bleibt getrennt, accountbezogen und verschluesselt. Haystack/Qdrant ist nur fuer Bibliotheksdokumente gedacht, also fuer Buecher, Handbuecher, PDFs und andere explizit abgelegte Referenzen.

Konfiguration in `Bot_Verhalten.md`:

```text
## Bibliothekar
- enabled: ja
- backend: local
- collection: teebotus_books
- qdrant_url: http://127.0.0.1:6333
- max_prompt_chars: 5000
- max_chunks: 5
- max_quote_chars: 900
- require_citations: ja
```

`backend: local` nutzt den JSONL-Store. `backend: haystack` oder `backend: qdrant` aktiviert den optionalen Haystack/Qdrant-Backendpfad hinter derselben `BibliothekarService`-Schnittstelle. Der lokale Store bleibt dabei die rebuildbare Quelle; Haystack/Qdrant ist ein Backend/Cache fuer produktivere Suche.

Vor dem Bibliothekar-Kontext kann ein optionaler Pydantic-Subtask `BibliothekarQueryDecision` laufen. Er entscheidet, ob der Quellenindex fuer die aktuelle natuerliche Sprache durchsucht werden soll, und kann die Suchfrage knapp normalisieren. Ohne strukturierten Runner bleibt das alte Verhalten erhalten: der Bibliothekar sucht weiter, sobald er in der Instanz aktiviert ist. Fuer echte Pydantic-AI-Laeufe gibt es `TeeBotus.ai_structures.build_pydantic_ai_model_runner(model)`. Der Adapter ist optional, nutzt Pydantic-AIs strukturierte `output_type`-Ausgabe und meldet klar, wenn das Extra `[agents]` nicht installiert ist.

CLI:

```bash
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot status
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot index --source /pfad/zu/buechern --dry-run
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot index --source /pfad/zu/buechern
python3 -m TeeBotus.bibliothekar --instances-dir instances --instance Depressionsbot query "Was steht zu Schlaf und Aktivierung?" --top-k 3
python3 -m TeeBotus.bibliothekar --instance Depressionsbot query --source tests/fixtures/books "Schlafhygiene Tagesstruktur" --top-k 3
python3 -m TeeBotus.bibliothekar --instance Depressionsbot query "System Therapie" --category psychologie --topic schlafhygiene --file therapie
```

`query --source` baut einen temporaeren lokalen Fixture-Index und veraendert die echte Instanz-Bibliothek nicht. Das ist fuer Akzeptanztests und Benchmarkvergleiche gedacht.
`query` kann mit `--category`, `--topic` und `--file` auf indexierte Metadaten eingeschraenkt werden; dieselben Filter laufen ueber den lokalen Store und das Haystack/Qdrant-Backend.

Haystack/Qdrant optional:

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

Pydantic-AI/LangGraph optional. Pydantic-Schemas werden nur fuer strukturierte Subtasks genutzt, darunter `IntentDecision`, `MemoryCandidate`, `ReminderDecision`, `BibliothekarQueryDecision` und `ProactiveToolCallDecision`; Slash-Commands bleiben klassische Parser.

```bash
python3 -m pip install '.[agents]'
```

Qdrant soll lokal auf `127.0.0.1` gebunden bleiben. `qdrant_url` darf nur auf `127.0.0.1`, `localhost` oder `::1` zeigen und keine Zugangsdaten, Query-Parameter oder Fragmente enthalten; nicht-lokale Ziele werden im Status als ungueltig gemeldet. Wenn Haystack/Qdrant konfiguriert, aber zur Laufzeit nicht verfuegbar ist, faellt die Suche auf den lokalen Bibliothekar zurueck, statt normale Botantworten zu crashen.

`python3 -m TeeBotus --runtime-status --channels telegram` prueft bei `backend: haystack` die optionalen Haystack/Qdrant-Abhaengigkeiten und die Qdrant-Erreichbarkeit. Bei erreichbarem Backend meldet der Status `store=qdrant target=http://127.0.0.1:6333 status=reachable` plus Dokument-/Chunk-Zahlen aus dem rebuildbaren lokalen Index; bei fehlendem oder nicht erreichbarem Backend meldet er `status=unavailable` oder `status=unreachable` mit Fehlertext.

LangGraph ist nicht der Botkern. Der erste Pilot liegt unter `TeeBotus/runtime/graphs/` und betrifft nur `Bibliothekar Deep Query`. Der Ablauf ist `classify -> retrieve -> rerank -> answer -> citation_check -> fallback`. Ohne installiertes `langgraph` laeuft derselbe serialisierbare State linear weiter. Normale Chatantworten, `/status`, `/help`, `/ping` und einfache Textregeln laufen nicht durch LangGraph.

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

Plan2-Extras sind absichtlich gepinnt. `litellm==1.83.7` verlangt `python-dotenv==1.0.1`; deshalb nutzt TeeBotus fuer strukturierte Pydantic-AI-Subtasks `pydantic-ai-slim==1.107.0` und fuer Tools `fastmcp==2.0.0`, statt die Full-Meta-Pakete zu installieren, die aktuell `python-dotenv>=1.1.0` ziehen.

Flex Processing wird ueber `service_tier: flex` in der aktiven Instanz-`Bot_Verhalten.md` aktiviert. Wegen der laengeren Laufzeit von Flex-Anfragen ist dort auch `timeout_seconds: 900` gesetzt.

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

Wenn ein User `/reset_memorys` sendet oder den Bot frei formuliert auffordert, seine Erinnerungen zu loeschen, fragt der Bot zuerst nach Bestaetigung. Erst nach einer klaren Antwort wie `ja` wird ausschliesslich das User-Memory der aktuellen Telegram-Sender-ID auf den initialen Skeletonzustand zurueckgesetzt: Index leer, JSONL leer. Admingepflegte interne Zusatzhinweise bleiben dabei unveraendert. Fremde User-Memorys und das Instanz-Arbeitsgedaechtnis werden nie durch User geloescht. Falls ein User danach fragt, weist der Bot darauf hin, dass das Instanz-/Arbeitsgedaechtnis keine userbezogenen Daten enthaelt.

## Instanz-Arbeitsgedaechtnis

Jede Instanz hat zusaetzlich ein gemeinsames Arbeitsgedaechtnis im eigenen `data`-Ordner:

- `instances/Bote_der_Wahrheit/data/Working_Memorys.json`
- `instances/Bote_der_Wahrheit/data/Working_Memorys.entries.jsonl`
- `instances/Depressionsbot/data/Working_Memorys.json`
- `instances/Depressionsbot/data/Working_Memorys.entries.jsonl`

Dieses Arbeitsgedaechtnis gilt fuer alle User derselben Instanz und darf deshalb keine User-IDs, Namen, Usernames, Chat-IDs, Chat-Titel, Rohzitate aus Usernachrichten oder eindeutig userbezogene Fakten enthalten.

Der Bot legt die Dateien beim Start automatisch an und nutzt vorhandene, ausgewaehlte Eintraege als eigene `Instanz-Arbeitsgedaechtnis`-Sektion im OpenAI-Kontext. Aktuell wird dieses globale Arbeitsgedaechtnis nicht automatisch aus Chats befuellt, weil die genaue Logik noch kuratiert werden muss. Manuell ergaenzte Eintraege werden im JSONL-Log gespeichert; der Index enthaelt Keywords, Recent-Liste und Byte-Positionen fuer gezieltes Lesen.

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
