# Telegram Bot

Ein kleiner Telegram-Bot in Python, ohne externe Abhaengigkeiten. Er nutzt Long Polling ueber die Telegram Bot API und kann mehrere Instanzen mit getrennten Einstellungen starten.

## Funktionen

- `/start` begruesst neue Nutzer
- `/help` zeigt die verfuegbaren Befehle
- `/ping` antwortet mit `pong`
- `/status` antwortet mit dem Status aus der aktiven Instanz-`BOT.md`
- `/chatid` zeigt die aktuelle Chat-ID
- `/reset` loescht den OpenAI-Verlauf fuer den aktuellen Chat
- `/delete_last` loescht die letzte gespeicherte Bot-Nachricht
- `/cleanup 10` loescht bis zu 10 gespeicherte Bot-Nachrichten
- `/voice Text` erzeugt eine Telegram-Sprachnachricht
- eingehende Telegram-Sprachnachrichten werden transkribiert und wie Textnachrichten verarbeitet
- normale Textnachrichten werden per aktiver Instanz-`BOT.md` beantwortet oder als Echo zurueckgegeben
- optionaler OpenAI-Fallback fuer freie Fragen

## Bot einrichten

1. In Telegram `@BotFather` oeffnen.
2. `/newbot` senden und den Anweisungen folgen.
3. Den Token in eine lokale `.env` kopieren:

```bash
cd telegram-bot
cp .env.example .env
```

4. `.env` bearbeiten und die instanzspezifischen Tokens ersetzen.
5. Fuer OpenAI-Antworten `OPENAI_API_KEY` setzen.

## Starten

Standard ist die Instanz `Bote_der_Wahrheit`:

```bash
cd telegram-bot
set -a
source .env
set +a
python3 -m telegram_bot
```

Eine bestimmte Instanz startest du so:

```bash
TELEGRAM_BOT_INSTANCE=Mondbot python3 -m telegram_bot
```

Fuer zwei parallel laufende Bots brauchst du zwei verschiedene Telegram-Bot-Tokens von `@BotFather`. Starte sie dann in zwei Terminals:

```bash
TELEGRAM_BOT_INSTANCE=Bote_der_Wahrheit python3 -m telegram_bot
```

```bash
TELEGRAM_BOT_INSTANCE=Mondbot python3 -m telegram_bot
```

Der Bot laeuft dann im Terminal. Mit `Ctrl+C` beendest du ihn.

Der Bot loggt nach `stdout`, wenn Telegram-Nachrichten eingehen oder Bot-Nachrichten ausgehen. Geloggt werden nur Metadaten wie Chat-ID, Message-ID, Nachrichtentyp und Laenge, nicht der Nachrichteninhalt.

## Verhalten steuern

Das Bot-Verhalten liegt pro Instanz in einer eigenen `BOT.md`:

- `instances/Bote_der_Wahrheit/BOT.md`
- `instances/Mondbot/BOT.md`

Diese lokalen Instanzdateien sind absichtlich per `.gitignore` vom Upload ausgeschlossen. Im Git-Repository liegt nur das generische Template `BOT.md`, damit keine echten Prompts, Regelwerke oder Secrets veroeffentlicht werden.

Die Datei funktioniert bewusst aehnlich wie eine `AGENTS.md`, aber fuer den laufenden Bot:

- `## Einstellungen` steuert Schalter wie `echo`.
- `## OpenAI` steuert OpenAI-Fallback, Modell und Ausgabeparameter.
- `## Antworten` steuert eingebaute Antworten wie `/start`, `/chatid` und unbekannte Befehle.
- `## Befehle` legt eigene Slash-Befehle an, z. B. `/status: Der Bot laeuft.`
- `## Systemprompt` steuert die Rolle und den Antwortstil des OpenAI-Modells.
- `## Textantworten` beantwortet exakte Texte ohne Slash-Befehl.
- `## Enthaelt` beantwortet Nachrichten, die einen bestimmten Text enthalten.
- `## Hilfe` steuert die Ausgabe von `/help`.

Der Bot laedt die aktive `BOT.md` automatisch neu, sobald sich die Datei geaendert hat und ein neues Telegram-Update ankommt.
Wenn ein Wert am Anfang oder Ende Leerzeichen behalten soll, setze ihn in Anfuehrungszeichen, zum Beispiel `echo_prefix: "Echo: "`.

Du kannst eine andere Instanz oder eine konkrete Datei verwenden:

```bash
TELEGRAM_BOT_INSTANCE=Mondbot python3 -m telegram_bot
```

```bash
TELEGRAM_BOT_INSTRUCTIONS=/pfad/zur/datei.md python3 -m telegram_bot
```

Token-Aufloesung:

- `TELEGRAM_BOT_TOKEN_BOTE_DER_WAHRHEIT` fuer `Bote_der_Wahrheit`
- `TELEGRAM_BOT_TOKEN_MONDBOT` fuer `Mondbot`
- `TELEGRAM_BOT_TOKEN` als allgemeiner Fallback fuer Einzelbetrieb

OpenAI-Key-Aufloesung:

- `OPENAI_API_KEY_BOTE_DER_WAHRHEIT` fuer `Bote_der_Wahrheit`
- `OPENAI_API_KEY_MONDBOT` fuer `Mondbot`
- `OPENAI_API_KEY` als allgemeiner Fallback

Unterstuetzte Platzhalter in Antworten:

- `{first_name}`
- `{last_name}`
- `{username}`
- `{name_suffix}`
- `{chat_id}`
- `{text}`

Freie normale Nachrichten gehen nur dann an OpenAI, wenn:

- `## OpenAI` den Wert `enabled: true` enthaelt,
- `OPENAI_API_KEY` gesetzt ist,
- keine Regel aus `## Textantworten` oder `## Enthaelt` passt.

Bei OpenAI-Nachrichten sendet der Bot zusaetzlich Telegram-Metadaten mit: Chat-ID, Chat-Typ, Chat-Titel, Absender-ID, Absendername und Username. Dadurch kann das Modell in Gruppenchats Nutzer auseinanderhalten.

Feste Slash-Befehle werden nicht an OpenAI gesendet.

Lange OpenAI-Antworten werden automatisch in mehrere Telegram-Nachrichten aufgeteilt, damit Telegrams Nachrichtenlimit nicht erreicht wird.

Sprachnachrichten werden mit `/voice Text` erzeugt. Alternativ kannst du auf eine Textnachricht antworten und nur `/voice` senden; der Bot vertont dann den Text der beantworteten Nachricht. Die Stimme wird in der aktiven Instanz-`BOT.md` ueber `voice_model`, `voice`, `voice_format`, `voice_speed` und `voice_instructions` gesteuert. Standard ist `voice_format: opus`, passend fuer Telegram-Sprachnachrichten.

Automatische Sprachnachrichten werden in der aktiven Instanz-`BOT.md` ueber `auto_voice_enabled`, `auto_voice_every`, `auto_voice_max_words` und `auto_voice_skip_sources` gesteuert. Aktuell wird jede dritte OpenAI-Antwort unter 50 Woertern ohne Quellen als Sprachnachricht gesendet.

Eingehende Telegram-Sprachnachrichten werden ueber OpenAI transkribiert und danach durch dieselbe Textlogik geschickt wie normale Nachrichten. Gesteuert wird das in der aktiven Instanz-`BOT.md` ueber `transcription_enabled`, `transcription_model`, `transcription_fallback_model`, `transcription_language`, `transcription_prompt`, `transcription_error` und `transcription_empty`. Wenn das erste Modell ein leeres Transkript liefert, versucht der Bot einmal `transcription_fallback_model`; mit leerem Wert wird dieser zweite Versuch abgeschaltet. Der transkribierte Inhalt wird nicht in die stdout-Logs geschrieben.

Flex Processing wird ueber `service_tier: flex` in der aktiven Instanz-`BOT.md` aktiviert. Wegen der laengeren Laufzeit von Flex-Anfragen ist dort auch `timeout_seconds: 900` gesetzt.

Websuche wird ueber `web_search: true` aktiviert. Mit `web_search_context_size: medium` bekommt das Modell einen mittleren Suchkontext. `web_search_required: false` laesst `tool_choice` auf `auto`, damit das Modell nur sucht, wenn es fuer die Antwort sinnvoll ist.

`rule_file: Gesprachsanalyse.md` bindet eine zusaetzliche Markdown-Datei neben der aktiven Instanz-`BOT.md` als Grundregelwerk fuer jede OpenAI-Unterhaltung ein. Der Bot laedt diese Datei zusammen mit `BOT.md` neu, sobald eine der beiden Dateien geaendert wurde.

Live-Validierung:

```bash
cd telegram-bot
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
cd telegram-bot
python3 -m unittest discover -s tests
```

## Anpassen

Normale Anpassungen gehen ueber die jeweilige Instanz-`BOT.md`. Code-Aenderungen brauchst du erst, wenn der Bot neue Faehigkeiten bekommen soll, zum Beispiel Datenbanken, HTTP-Abfragen oder Admin-Rechte.
