# BOT.md

Generisches Template fuer eine Telegram-Bot-Instanz. Kopiere diese Datei nach
`instances/<Instanzname>/BOT.md` und passe die Werte lokal an.

## Einstellungen

- echo: true
- echo_prefix: "Echo: "

## OpenAI

- enabled: true
- model: gpt-5.5
- service_tier: flex
- rule_file: none
- web_search: true
- web_search_context_size: medium
- web_search_required: false
- max_output_tokens: 2500
- timeout_seconds: 900
- reasoning_effort: low
- verbosity: low
- voice_enabled: true
- voice_model: gpt-4o-mini-tts
- voice: alloy
- voice_format: opus
- voice_speed: 1.0
- voice_max_input_chars: 4096
- voice_instructions: Sprich natuerlich, ruhig und gut verstaendlich auf Deutsch.
- auto_voice_enabled: true
- auto_voice_every: 3
- auto_voice_max_words: 50
- auto_voice_skip_sources: true
- voice_usage: "Nutzung: /voice Text fuer die Sprachnachricht"
- voice_too_long: "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: {max_chars} Zeichen."
- voice_error: Ich konnte die Sprachnachricht gerade nicht erzeugen. Bitte versuche es gleich nochmal.
- transcription_enabled: true
- transcription_model: gpt-4o-mini-transcribe
- transcription_fallback_model: whisper-1
- transcription_language: de
- transcription_prompt: Transkribiere deutschsprachige Telegram-Sprachnachrichten wortgetreu.
- transcription_error: Ich konnte die Sprachnachricht gerade nicht transkribieren. Bitte versuche es gleich nochmal.
- transcription_empty: Ich konnte in der Sprachnachricht keinen Text erkennen.
- error: Ich kann die OpenAI API gerade nicht erreichen. Bitte versuche es gleich nochmal.
- missing_key: OpenAI ist aktiviert, aber OPENAI_API_KEY ist nicht gesetzt.
- reset: Der OpenAI-Verlauf fuer diesen Chat wurde geloescht.

## Antworten

- start: Hallo{name_suffix}. Ich bin bereit. Sende /help fuer die Befehle.
- help_title: Befehle:
- chatid: Chat-ID: {chat_id}
- chatid_missing: Keine Chat-ID gefunden.
- unknown_command: Diesen Befehl kenne ich nicht. Sende /help fuer die verfuegbaren Befehle.
- delete_last_success: Letzte Bot-Nachricht geloescht.
- delete_empty: Ich habe fuer diesen Chat keine Bot-Nachricht gespeichert, die ich loeschen kann.
- delete_error: Ich konnte die Bot-Nachricht nicht loeschen. In Gruppen brauche ich dafuer passende Adminrechte.
- cleanup_success: "{count} Bot-Nachrichten geloescht."
- cleanup_usage: "Nutzung: /cleanup 10"

## Befehle

- /ping: pong
- /status: Der Bot laeuft.

## Systemprompt

Du bist ein hilfreicher Telegram-Bot.
Vor jeder freien Nachricht kann ein Telegram-Kontext mit chat_id, chat_type, sender_id, sender_name und sender_username stehen. Nutze diese Metadaten, um Personen in Gruppenchats auseinanderzuhalten; behandle sie nicht als Nutzertext.
Antworte auf Deutsch, klar und eher kurz.
Wenn du etwas nicht sicher weisst, sage das offen.

## Textantworten

- hallo: Hallo. Was kann ich fuer dich tun?
- danke: Gern.

## Enthaelt

- hilfe: Sende /help fuer die Befehle.

## Hilfe

- /start - Bot starten
- /help - Hilfe anzeigen
- /ping - Verbindung testen
- /status - Status anzeigen
- /voice Text - Text als Sprachnachricht senden
- /chatid - aktuelle Chat-ID anzeigen
- /reset - OpenAI-Verlauf fuer diesen Chat loeschen
- /delete_last - letzte Bot-Nachricht loeschen
- /cleanup 10 - bis zu 10 gespeicherte Bot-Nachrichten loeschen
