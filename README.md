# TeeBotus

TeeBotus ist ein kleiner Telegram-Bot in Python, ohne externe Abhaengigkeiten. Er nutzt Long Polling ueber die Telegram Bot API und kann mehrere Instanzen mit getrennten Einstellungen starten.

## Funktionen

- `/start` begruesst neue Nutzer
- `/help` zeigt die verfuegbaren Befehle
- `/ping` antwortet mit `pong`
- `/status` zeigt Laufstatus, TeeBotus-Version, GitHub-Commithistorie, Memory-Groesse und Userfile-Verschluesselung des anfragenden Nutzers
- `/chatid` zeigt die aktuelle Chat-ID
- `/reset` loescht den OpenAI-Verlauf fuer den aktuellen Chat
- `/reset_memorys` fragt nach und loescht danach nur die eigenen User-Memory-Eintraege
- frei formulierte Bitten wie `loesch meine Erinnerungen` nutzen denselben bestaetigten User-Memory-Reset
- `/Call_a_Teladi` fragt nach einer Emergency Message und leitet die naechste Telegram-Nachricht an Teladi weiter
- `/cleanup N` loescht die letzten N seit Bot-Start gemerkten Nachrichten aus dem aktuellen Chat
- `/cleanup all` loescht alle zuletzt gemerkten Nachrichten aus dem aktuellen Chat
- `/codex Prompt` startet lokal `codex exec` aus dem Bot-Prozess heraus
- `/voice Text` erzeugt eine Telegram-Sprachnachricht
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

`TeeBotus/bot.py` bleibt der stabile Entry-Point. Telegram laeuft weiter ueber `TeeBotus/adapters/telegram_polling.py`; konfigurierte Signal- und Matrix-Slots koennen zusaetzlich ueber die Plan3-Runtime gestartet werden.

Die Runtime-Konfiguration kannst du separat pruefen:

```bash
python3 -m TeeBotus --runtime-status --channels telegram
```

`--channels telegram` startet nur Telegram. `--channels signal` startet nur konfigurierte Signal-Slots. `--channels matrix` startet nur konfigurierte Matrix-Slots. Kombinationen mit Telegram starten die zusaetzlichen Slots im Hintergrund und danach den stabilen Telegram-Poller.

Signal braucht das Python-Paket `signalbot`, die native `signal-cli-api` und `signal-cli`. Die festen Versionen stehen in `adapter-dependencies.lock`; die Python-Adapter-Abhaengigkeiten koennen reproduzierbar installiert und danach geprueft werden mit:

```bash
python3 scripts/install_adapter_deps.py
python3 scripts/check_adapter_deps.py
```

`nio-bot 1.0.2.post1` deklariert upstream noch `matrix-nio==0.20.*`. TeeBotus prueft aktuell den echten Runtime-Override `matrix-nio==0.25.0` mit `h11==0.16.0`, weil unsere genutzten `nio-bot`-/`matrix-nio`-Vertraege damit laufen und die moderne `httpcore`-/`httpx`-Kette importierbar bleibt. `scripts/install_adapter_deps.py` installiert `nio-bot` deshalb gezielt ohne dessen alte `matrix-nio`-Abhaengigkeit und laesst danach `scripts/check_adapter_deps.py` laufen.

Native Abhaengigkeiten werden weiter separat installiert und mit demselben Check verifiziert.

Pro Instanz muessen Service-URL und Telefonnummer zusammen gesetzt sein:

```bash
SIGNAL_BOT_SERVICE_DEPRESSIONSBOT=http://127.0.0.1:8080
SIGNAL_BOT_PHONE_NUMBER_DEPRESSIONSBOT=+49...
```

Die Erreichbarkeit des externen Signal-Dienstes pruefst du ohne Botstart:

```bash
python3 -m TeeBotus --runtime-status --channels signal
```

Wenn ein lokaler konfigurierter Signal-Dienst nicht erreichbar ist, startet TeeBotus `signal-cli-api --listen <host>:<port>` automatisch und prueft danach erneut. Fuer nicht-lokale Services bleibt ein nicht erreichbares Backend ein harter Startfehler. `signalbot` nutzt dabei `InMemoryConfig`; persistenter Bot-Zustand liegt in TeeBotus, Signal-Account-Daten liegen bei `signal-cli`.

`--runtime-status --channels signal` meldet zusaetzlich den Signal-Account-Zustand:

```text
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=registered
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=missing
signal_account=<instance>/<slot> phone=+49... target=127.0.0.1:8080 status=unavailable
```

`missing` bedeutet: das Backend ist erreichbar, aber `signal-cli-api` listet die konfigurierte Telefonnummer nicht in `/v1/accounts`. Dann muss der native Signal-Account zuerst in `signal-cli` eingerichtet werden. Als Primaergeraet:

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

Account-Report:

```bash
python3 -m TeeBotus.admin accounts report --instances-dir instances
```

Der Report liest den AccountStore read-only und erzeugt keine neuen Secrets.

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

Sprachnachrichten werden mit `/voice Text` erzeugt. Alternativ kannst du auf eine Textnachricht antworten und nur `/voice` senden; der Bot vertont dann den Text der beantworteten Nachricht. Die Stimme wird in der aktiven Instanz-`Bot_Verhalten.md` ueber `voice_model`, `voice`, `voice_format`, `voice_speed` und `voice_instructions` gesteuert. Standard ist `voice_format: opus`, passend fuer Telegram-Sprachnachrichten.

`/codex Prompt` startet den lokalen Codex-CLI-Prozess aus dem Bot-Prozess heraus. Zugelassen sind nur die in der aktiven Instanz-`Bot_Verhalten.md` unter `## Codex` eingetragenen Telegram-Sender-IDs. Der Bot arbeitet dabei aus dem Repository-Root und benutzt kein `shell=True`.

Automatische Sprachnachrichten werden in der aktiven Instanz-`Bot_Verhalten.md` ueber `auto_voice_enabled`, `auto_voice_every`, `auto_voice_max_words` und `auto_voice_skip_sources` gesteuert. Aktuell wird jede dritte OpenAI-Antwort unter 50 Woertern ohne Quellen als Sprachnachricht gesendet.

Eingehende Telegram-Sprachnachrichten werden ueber OpenAI transkribiert und danach durch dieselbe Textlogik geschickt wie normale Nachrichten. Gesteuert wird das in der aktiven Instanz-`Bot_Verhalten.md` ueber `transcription_enabled`, `transcription_model`, `transcription_fallback_model`, `transcription_language`, `transcription_prompt`, `transcription_error` und `transcription_empty`. Wenn das erste Modell ein leeres Transkript liefert, versucht der Bot einmal `transcription_fallback_model`; mit leerem Wert wird dieser zweite Versuch abgeschaltet. Der transkribierte Inhalt wird nicht in die stdout-Logs geschrieben. Audio-Dateien werden nicht gespeichert; im User-Memory landet nur das Transkript als Text.

YouTube-Transkripte laufen zweistufig: Zuerst versucht der Bot mit `yt-dlp` vorhandene YouTube-Untertitel zu laden. Wenn keine Untertitel gefunden werden, fragt er vor lokaler Transkription nach Live-Ausgabe und LLM-Weitergabe. Lokale Transkription laeuft ueber `faster-whisper` mit Modell `tiny`, automatischer Sprachwahl fuer Deutsch/Englisch, maximal zwei CPU-Threads, `nice -n 19` und, falls vorhanden, `ionice -c 3`. Der lokale Transkriptionsjob laeuft in einem Hintergrund-Worker; Telegram-Polling bleibt aktiv. Timeout ist `7200` Sekunden. Nach 5, 15, 60 und 90 Minuten prueft ein Watchdog, ob der Child-Prozess noch plausibel lebt. Wenn nicht, beendet der Bot die Prozessgruppe und meldet den Fehler im Chat. Reine Python-`resource_tracker`-Warnungen beim Abbruch werden aus dem Telegram-Fehlertext herausgefiltert.

Wenn der Freitext-Parser Live-Ausgabe oder LLM-Weitergabe nicht vollstaendig erkennt, kann ein vorhandener OpenAI-Client die beiden Optionen eng als JSON klassifizieren. Parser-Ergebnisse gewinnen dabei; das LLM fuellt nur fehlende Werte. Solche nachtraeglich erkannten Formulierungen werden URL-redaktiert in `instances/{instance}/data/YouTube_Parser_Misses.jsonl` protokolliert und instanzlokal wieder vom Parser gelesen, damit dieselbe Formulierung beim naechsten Mal ohne LLM-Fallback erkannt wird. Der Wiedererkennungsabgleich ist konservativ tokenbasiert und ignoriert URL- und Befehlsfuelltext, verlangt aber mehrere spezifische Tokens.

Die zaehlbaren Grundformen des Live/LLM-Parsers koennen mit `python3 scripts/youtube_parser_stats.py` oder maschinenlesbar mit `python3 scripts/youtube_parser_stats.py --json` neu berechnet werden. Die konkrete Sprache bleibt wegen freier Regex-Zwischenraeume, Learned-Phrases und LLM-Fallback unendlich; das Skript weist deshalb eine konservative zaehlbare Untergrenze aus.

Der aktuelle Bestand gelernter Parser-Misses kann mit `python3 scripts/youtube_parser_misses_report.py --instances-dir instances` ausgewertet werden. Der Report gruppiert Formulierungen, zeigt ob der Basisparser sie inzwischen direkt erkennt, markiert verbleibende Kandidaten fuer dauerhafte Parser-Regeln und gibt pro Kandidat eine kompakte Promotion-Suggestion mit Zielwerten und spezifischen Tokens aus. Mit `--regression-json` erzeugt der Report eine kompakte Testfall-Liste; mit `--pytest-snippet` erzeugt er direkt einen einfuegbaren `pytest.mark.parametrize`-Block fuer Parser-Regressionen.

Flex Processing wird ueber `service_tier: flex` in der aktiven Instanz-`Bot_Verhalten.md` aktiviert. Wegen der laengeren Laufzeit von Flex-Anfragen ist dort auch `timeout_seconds: 900` gesetzt.

Websuche wird ueber `web_search: true` aktiviert. Mit `web_search_context_size: medium` bekommt das Modell einen mittleren Suchkontext. `web_search_required: false` laesst `tool_choice` auf `auto`, damit das Modell nur sucht, wenn es fuer die Antwort sinnvoll ist.

`rule_file: Bot_Rüstzeug.md` bindet eine zusaetzliche Markdown-Datei neben der aktiven Instanz-`Bot_Verhalten.md` als Grundregelwerk fuer jede OpenAI-Unterhaltung ein. Der Bot laedt diese Datei zusammen mit `Bot_Verhalten.md` neu, sobald eine der beiden Dateien geaendert wurde.

## User-Memory

Der Account-Layer speichert accountbezogene Daten unter `instances/<instance>/data/accounts/accounts/<account_id>/`.

Strukturierte Accountdaten werden verschluesselt gespeichert. Interne operatorgepflegte Hinweise sind eine separate Vertrauensebene und werden Usern nicht mit Dateinamen offengelegt.

Die strukturierten AccountStore-Schluessel liegen instanzgebunden im Desktop Secret Service via `secret-tool`. Das alte senderbezogene `User_Memory_Key.bin`-Backend wird nicht mehr genutzt.

Der Speicher ist accountbezogen und nicht mehr an `data/users/<telegram_sender_id>` gebunden. `instances/*/data/` ist per `.gitignore` ausgeschlossen.

Mehr zur Datenhaltung, zum Schluesselmodell und zu den Grenzen der Verschluesselung steht in [docs/privacy-and-encryption.md](docs/privacy-and-encryption.md).

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
python3 -m unittest discover -s tests
```

## Anpassen

Normale Anpassungen gehen ueber die jeweilige Instanz-`Bot_Verhalten.md`. Code-Aenderungen brauchst du erst, wenn der Bot neue Faehigkeiten bekommen soll, zum Beispiel Datenbanken, HTTP-Abfragen oder Admin-Rechte.
