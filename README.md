# Telegram Bot

Ein kleiner Telegram-Bot in Python, ohne externe Abhaengigkeiten. Er nutzt Long Polling ueber die Telegram Bot API und kann mehrere Instanzen mit getrennten Einstellungen starten.

## Funktionen

- `/start` begruesst neue Nutzer
- `/help` zeigt die verfuegbaren Befehle
- `/ping` antwortet mit `pong`
- `/status` antwortet mit dem Status aus der aktiven Instanz-`Bot_Verhalten.md`
- `/chatid` zeigt die aktuelle Chat-ID
- `/reset` loescht den OpenAI-Verlauf fuer den aktuellen Chat
- `/reset_memorys` fragt nach und loescht danach nur die eigenen User-Memory-Eintraege
- frei formulierte Bitten wie `loesch meine Erinnerungen` nutzen denselben bestaetigten User-Memory-Reset
- `/Call_a_Teladi` fragt nach einer Emergency Message und leitet die naechste Telegram-Nachricht an Teladi weiter
- `/delete_last` loescht die letzte gespeicherte Bot-Nachricht
- `/cleanup 10` loescht bis zu 10 gespeicherte Bot-Nachrichten
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

Standard ist die Instanz `Bote_der_Wahrheit`:

```bash
cd TeeBotus
set -a
source .env
set +a
python3 -m telegram_bot
```

Eine bestimmte Instanz startest du so:

```bash
TELEGRAM_BOT_INSTANCE=Depressionsbot python3 -m telegram_bot
```

Fuer zwei parallel laufende Bots brauchst du zwei verschiedene Telegram-Bot-Tokens von `@BotFather`. Starte sie dann in zwei Terminals:

```bash
TELEGRAM_BOT_INSTANCE=Bote_der_Wahrheit python3 -m telegram_bot
```

```bash
TELEGRAM_BOT_INSTANCE=Depressionsbot python3 -m telegram_bot
```

Der Bot laeuft dann im Terminal. Mit `Ctrl+C` beendest du ihn.

Der Bot loggt nach `stdout`, wenn Telegram-Nachrichten eingehen oder Bot-Nachrichten ausgehen. Geloggt werden nur Metadaten wie Chat-ID, Message-ID, Nachrichtentyp und Laenge, nicht der Nachrichteninhalt.

## Verhalten steuern

Das Bot-Verhalten liegt pro Instanz in einer eigenen `Bot_Verhalten.md`:

- `instances/Bote_der_Wahrheit/Bot_Verhalten.md`
- `instances/Depressionsbot/Bot_Verhalten.md`

Diese lokalen Instanzdateien sind absichtlich per `.gitignore` vom Upload ausgeschlossen. Im Git-Repository liegt nur das generische Template `Bot_Verhalten.md`, damit keine echten Prompts, Regelwerke oder Secrets veroeffentlicht werden.

Die Datei funktioniert bewusst aehnlich wie eine `AGENTS.md`, aber fuer den laufenden Bot:

- `## Einstellungen` steuert Schalter wie `echo`.
- `## OpenAI` steuert OpenAI-Fallback, Modell und Ausgabeparameter.
- `## Antworten` steuert eingebaute Antworten wie `/start`, `/chatid` und unbekannte Befehle.
- `## Befehle` legt eigene Slash-Befehle an, z. B. `/status: Der Bot laeuft.`
- `## Systemprompt` steuert die Rolle und den Antwortstil des OpenAI-Modells.
- `## Textantworten` beantwortet exakte Texte ohne Slash-Befehl.
- `## Enthaelt` beantwortet Nachrichten, die einen bestimmten Text enthalten.
- `## Hilfe` steuert die Ausgabe von `/help`.

Der Bot laedt die aktive `Bot_Verhalten.md` automatisch neu, sobald sich die Datei geaendert hat und ein neues Telegram-Update ankommt.
Wenn ein Wert am Anfang oder Ende Leerzeichen behalten soll, setze ihn in Anfuehrungszeichen, zum Beispiel `echo_prefix: "Echo: "`.

Du kannst eine andere Instanz oder eine konkrete Datei verwenden:

```bash
TELEGRAM_BOT_INSTANCE=Depressionsbot python3 -m telegram_bot
```

```bash
TELEGRAM_BOT_INSTRUCTIONS=/pfad/zur/datei.md python3 -m telegram_bot
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

Flex Processing wird ueber `service_tier: flex` in der aktiven Instanz-`Bot_Verhalten.md` aktiviert. Wegen der laengeren Laufzeit von Flex-Anfragen ist dort auch `timeout_seconds: 900` gesetzt.

Websuche wird ueber `web_search: true` aktiviert. Mit `web_search_context_size: medium` bekommt das Modell einen mittleren Suchkontext. `web_search_required: false` laesst `tool_choice` auf `auto`, damit das Modell nur sucht, wenn es fuer die Antwort sinnvoll ist.

`rule_file: Bot_Rüstzeug.md` bindet eine zusaetzliche Markdown-Datei neben der aktiven Instanz-`Bot_Verhalten.md` als Grundregelwerk fuer jede OpenAI-Unterhaltung ein. Der Bot laedt diese Datei zusammen mit `Bot_Verhalten.md` neu, sobald eine der beiden Dateien geaendert wurde.

## User-Memory

Eine Instanz kann pro Telegram-Absender ein lokales JSON-Gedaechtnis fuehren. Konfiguriert wird das in `## Memory`:

- `enabled: true` aktiviert den Speicher.
- `directory: instances/{instance}/data/users` legt den Speicherort fest.
- `max_prompt_chars` begrenzt die ausgewaehlte JSON-Auswahl, die an OpenAI mitgegeben wird.
- `max_entry_chars` begrenzt gespeicherte Einzelauszuege.

Pro Telegram-Sender-ID gibt es einen eigenen Ordner, zum Beispiel `instances/Depressionsbot/data/users/123456789/`. Darin liegen ein JSON-Index, ein JSONL-Eintragslog und eine interne, admingepflegte Zusatzhinweis-Datei.

Diese ID ist fuer Telegram-User stabiler als ein Username, weil Usernames geaendert werden koennen. Der Bot laedt fuer eine Interaktion nur Index, ausgewaehlte Eintraege und interne Zusatzhinweise der aktuellen `sender_id`; Nutzer bekommen keinen Zugriff auf Memory-Dateien anderer Sender-IDs.

Die Index-Datei enthaelt Profilmetadaten, Keyword-Index, Recent-Liste und Byte-Positionen der JSONL-Eintraege. Dadurch kann der Bot gezielt relevante Eintraege fuer die aktuelle Nachricht auswaehlen und nur diese aus dem JSONL-Log lesen, statt immer das ganze Dokument oder nur die letzten Zeichen mitzuschicken. Die internen Zusatzhinweise werden nur von Botadmins gepflegt und dienen dem Bot als stiller Kontext. Der Speicher wird ueber unterschiedliche Chats, Gruppen und mehrere Bot-Tokens derselben Instanz hinweg geteilt, aber nur fuer dieselbe Telegram-Sender-ID. `instances/*/data/` ist per `.gitignore` ausgeschlossen.

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
python3 -m telegram_bot --all
```

Der Bot sucht dabei nach `instances/*/Bot_Verhalten.md`. Instanzen ohne Telegram-Token werden uebersprungen; bei fehlerhaften OpenAI-Key-Slots bricht der Start mit einer Meldung ab.

Live-Validierung:

```bash
cd TeeBotus
python3 scripts/validate_flex.py
```

## Nachrichten loeschen

Der Bot merkt sich die `message_id` seiner eigenen Antworten im Arbeitsspeicher. Damit funktionieren:

- `/delete_last` loescht die letzte gespeicherte Bot-Nachricht im aktuellen Chat.
- `/cleanup 10` loescht bis zu 10 gespeicherte Bot-Nachrichten im aktuellen Chat.

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
