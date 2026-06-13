# Bot_Verhalten.md

Generisches Template fuer eine Telegram-Bot-Instanz. Kopiere diese Datei nach
`instances/<Instanzname>/Bot_Verhalten.md` und passe die Werte lokal an.

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
- reset: Der OpenAI-Verlauf fuer diesen Chat wurde geloescht. Das betrifft nur den Antwortkontext fuer OpenAI in diesem Chat; Telegram-Nachrichten und User-Memory bleiben erhalten.

## Antworten

- start: Hallo{name_suffix}. Ich bin bereit. Sende /help fuer die Befehle.
- help_title: Befehle:
- chatid: Chat-ID: {chat_id}
- chatid_missing: Keine Chat-ID gefunden.
- unknown_command: Diesen Befehl kenne ich nicht. Sende /help fuer die verfuegbaren Befehle.
- delete_last_success: Letzte gespeicherte Bot-Nachricht geloescht. Das entfernt nur eine Telegram-Nachricht des Bots aus diesem Chat; OpenAI-Verlauf und User-Memory bleiben erhalten.
- delete_empty: Ich habe fuer diesen Chat keine gespeicherte Nachricht, die ich loeschen kann. /delete_last und /cleanup arbeiten mit den seit dem letzten Bot-Start gemerkten Nachrichten in diesem Chat.
- delete_error: Ich konnte die Bot-Nachricht nicht loeschen. In Gruppen brauche ich dafuer passende Adminrechte; OpenAI-Verlauf und User-Memory bleiben dabei erhalten.
- cleanup_success: "{count} gespeicherte Nachrichten geloescht. Das entfernt die gemerkten Telegram-Nachrichten aus diesem Chat; OpenAI-Verlauf und User-Memory bleiben erhalten."
- cleanup_usage: "Nutzung: /cleanup N. Damit loesche ich bis zu N seit dem letzten Bot-Start gemerkte Nachrichten aus diesem Chat."
- codex_usage: "Nutzung: /codex Prompt"
- codex_unauthorized: Nein.
- codex_not_found: Codex CLI wurde nicht gefunden.
- codex_error: "Codex konnte gerade nicht ausgefuehrt werden: {error}"
- codex_empty: Codex hat keine Ausgabe erzeugt.
- user_memory_reset_confirm: Soll ich deine gespeicherten User-Memory-Eintraege wirklich loeschen? Das betrifft nur deine eigenen Memory-Eintraege; OpenAI-Verlauf, Telegram-Nachrichten und admingepflegte interne Hinweise bleiben erhalten. Antworte mit Ja zum Loeschen oder Nein zum Abbrechen.
- user_memory_reset_success: Deine gespeicherten User-Memory-Eintraege wurden geloescht. OpenAI-Verlauf, Telegram-Nachrichten und admingepflegte interne Hinweise bleiben erhalten.
- user_memory_reset_cancelled: Okay, ich loesche nichts. Deine User-Memory-Eintraege bleiben erhalten.
- user_memory_reset_unavailable: Fuer dich ist kein User-Memory aktiv. Es wurden keine Telegram-Nachrichten und kein OpenAI-Verlauf geloescht.
- user_memory_reset_error: Ich konnte deine User-Memory-Eintraege gerade nicht loeschen. Bitte versuche es spaeter erneut.
- user_memory_reset_only_own: Ich kann nur deine eigenen Erinnerungen loeschen, nicht fremde Erinnerungen oder das Instanz-Arbeitsgedaechtnis. Das Instanz-/Arbeitsgedaechtnis enthaelt keine userbezogenen Daten.
- teladi_call_prompt: Welche Emergency Message soll ich an Teladi schicken? Deine naechste Antwort wird 1:1 weitergeleitet.
- teladi_call_sent: Emergency Message wurde an Teladi gesendet.
- teladi_call_cooldown: Du kannst /Call_a_Teladi erst in {remaining} wieder nutzen.
- teladi_call_error: Ich konnte die Emergency Message gerade nicht senden. Bitte versuche es spaeter erneut.

## Memory

- enabled: false
- directory: instances/{instance}/data/users
- max_prompt_chars: 12000
- max_entry_chars: 2000

## Befehle

- /ping: pong
- /status: Der Bot laeuft.

## Codex

- enabled: true
- allowed_sender_ids: 395935293
- timeout_seconds: 300

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
- /voice Text - Text als Sprachnachricht senden; ohne Text wird die beantwortete Nachricht vertont
- /codex Prompt - fuehrt Codex CLI lokal aus
- /youtube_transcript URL - YouTube-Untertitel laden oder per lokalem Whisper transkribieren
- /chatid - aktuelle Chat-ID anzeigen
- /reset - nur OpenAI-Verlauf dieses Chats zuruecksetzen; Memory und Telegram-Nachrichten bleiben erhalten
- /reset_memorys - nach Rueckfrage nur deine eigenen User-Memory-Eintraege loeschen
- /Call_a_Teladi - Send Teladi a emergency message
- /delete_last - nur die letzte seit Bot-Start gemerkte Bot-Nachricht in diesem Chat loeschen
- /cleanup N - bis zu N seit Bot-Start gemerkte Nachrichten in diesem Chat loeschen
