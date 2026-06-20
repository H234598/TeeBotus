# Bot_Verhalten.md

Diese Datei steuert das Laufzeitverhalten der Instanz TeeBotus_Logger.

## Einstellungen

- bot_aliases: TBL, tl, telo, TeeBotus Logger, TeeBotus-Logger
- user_memory_enabled: true
- user_memory_max_prompt_chars: 12000
- user_memory_max_entry_chars: 2000

## Memory Search

- semantic_enabled: true
- semantic_backend: qdrant
- embedding_provider: hash
- embedding_model: teebotus-account-memory-hash
- embedding_dimensions: 64

## OpenAI

- enabled: true
- voice: onyx
- transcription_backend: local
- local_transcription_model: tiny
- transcription_language: de

## Antworten

- start: Hallo{name_suffix}. Ich bin TeeBotus Logger. Sende /help fuer die Befehle.
- user_memory_error: Ich kann dein User-Memory gerade nicht laden oder speichern. Ich antworte ohne gespeicherte Erinnerungen; vorhandene Memory-Dateien werden nicht geloescht.

## Befehle

- /status: TeeBotus Logger laeuft.

## Systemprompt

Du bist TeeBotus Logger, kurz TBL.
Antworte auf Deutsch, knapp und technisch klar.
Deine Aufgabe ist Admin-, Runtime-, Release- und Projekt-History-Kommunikation fuer TeeBotus.
Gib keine Secrets, Tokens oder privaten Userdaten aus.

## Hilfe

- /start - Bot starten
- /help - Hilfe anzeigen
- /ping - Verbindung testen
- /status - Bot-Status, Version, Memory-Groesse und Userfile-Verschluesselung anzeigen
- /account - TeeBotus-Account und verknuepfte Kommunikationswege anzeigen
- /register - Account-Secret erzeugen und anzeigen
- /login <account_id> <secret> - diesen Kommunikationsweg mit einem Account verbinden
- /rotate_secret - neues Account-Secret erzeugen
- /linked_accounts - verknuepfte Kommunikationswege anzeigen
- /account_edit - Account-Verknuepfungen bearbeiten
- /chatid - aktuelle Chat-ID anzeigen
- /reset - setzt nur den Text-LLM-Kontext dieses Chats zurueck. Memory und Telegram-Nachrichten bleiben erhalten.
- /reset_memorys - fragt nach und loescht danach nur deine eigenen User-Memory-Eintraege.
