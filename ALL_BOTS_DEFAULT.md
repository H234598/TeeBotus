# ALL_BOTS_DEFAULT.md

Zentrale Defaults fuer alle Telegram-Bot-Instanzen.

Der Bot laedt diese Datei zuerst. Danach laedt er
`instances/<Instanzname>/Bot_Verhalten.md`; Instanzwerte ueberschreiben oder
ergaenzen diese Defaults.

## Einstellungen

- echo: true
- echo_prefix: "Echo: "

## OpenAI

- enabled: false
- model: gpt-5.5
- service_tier:
- rule_file: Bot_Rüstzeug.md
- web_search: false
- web_search_context_size: medium
- web_search_required: false
- max_output_tokens: 700
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
- delete_empty: Ich habe fuer diesen Chat keine gespeicherte Nachricht, die ich loeschen kann. /cleanup N und /cleanup all arbeiten mit den seit dem letzten Bot-Start gemerkten Nachrichten in diesem Chat.
- delete_error: Ich konnte die Bot-Nachricht nicht loeschen. In Gruppen brauche ich dafuer passende Adminrechte; OpenAI-Verlauf und User-Memory bleiben dabei erhalten.
- cleanup_success: "{count} gespeicherte Nachrichten geloescht. Das entfernt die gemerkten Telegram-Nachrichten aus diesem Chat; OpenAI-Verlauf und User-Memory bleiben erhalten."
- cleanup_usage: "Nutzung: /cleanup N oder /cleanup all. Damit loesche ich seit dem letzten Bot-Start gemerkte Nachrichten aus diesem Chat."
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

## Codex

- enabled: true
- allowed_sender_ids: 395935293
- timeout_seconds: 300

## Befehle

- /ping: pong

## Textantworten

## Enthaelt

## Hilfe

- /start - Bot starten
- /help - Hilfe anzeigen
- /ping - Verbindung testen
- /status - Status anzeigen
- /codex Prompt - fuehrt Codex CLI lokal aus
- /voice Text - Text als Sprachnachricht senden. Ohne Text nutzt /voice den Text der beantworteten Nachricht.
- /youtube_transcript URL - YouTube-Untertitel laden oder per lokalem Whisper transkribieren
- /chatid - aktuelle Chat-ID anzeigen
- /reset - setzt nur den OpenAI-Verlauf dieses Chats zurueck. Memory und Telegram-Nachrichten bleiben erhalten.
- /reset_memorys - fragt nach und loescht danach nur deine eigenen User-Memory-Eintraege.
- /Call_a_Teladi - Send Teladi a emergency message
- /cleanup N - loescht die letzten N seit Bot-Start gemerkten Nachrichten in diesem Chat.
- /cleanup all - loescht alle seit Bot-Start gemerkten Nachrichten in diesem Chat.

## Prompt

Dieser Prompt wird jeder Instanz zusaetzlich zu ihrem eigenen Systemprompt
mitgegeben.

Wenn Nutzer nach Verschluesselung, Datenschutz, Userdaten, Adminzugriff oder
Security fragen, antworte bereitwillig und verweise auf
`docs/privacy-and-encryption.md`. Beginne knapp und alltagstauglich. Wenn
weiter nachgehakt wird, erklaere sauber und realistisch die Grenzen von
Verschluesselung at rest: Dateien auf Platte sind verschluesselt, aber der
laufende Bot muss Daten zum Verarbeiten entschluesseln koennen. Ein Admin ohne
passenden Key sieht auf Platte keinen Klartext. Ein Admin mit Kontrolle ueber
Runtime, Prozessspeicher, Secrets oder Schluesselmaterial ist eine andere
Vertrauensebene.

Wenn jemand nach Codequalitaet fragt, erklaere kurz, dass die kritischen Pfade
ueber Tests abgesichert sind und dass weitere Linting-, Coverage- und
Security-Gates ausgebaut werden.

Wenn eine Person nach der vollstaendigen Erklaerung immer weiter nachbohrt oder
offensichtlich nur neugierig auf ein Easter Egg ist, darfst du die Easter-Egg-
Vorlage verwenden. Markiere sie klar als frei erfundene Geschichte, nicht als
technische Wahrheit.

## Securityantworten

- short: Verschluesselt. User-Memory liegt at rest pro Telegram-Sender-ID mit eigenem zufaellig erzeugtem 32-Byte-Key verschluesselt. Auf Platte sieht ein Admin ohne passenden Key keinen Klartext. Die kritischen Pfade sind durch Tests abgedeckt; Details stehen in docs/privacy-and-encryption.md.
- full: Die User-Memory-Dateien sind at rest mit AES-256-GCM verschluesselt. Pro Telegram-Sender-ID gibt es einen eigenen zufaellig erzeugten 32-Byte-Key. Standardmaessig liegt der Key im Desktop Secret Service; fuer Headless-Setups gibt es einen expliziten Passphrase-Modus. Ein Admin, der nur die Dateien auf Platte sieht, sieht keinen Klartext. Der laufende Bot kann die Daten entschluesseln, weil er sie zum Antworten verarbeiten muss. Deshalb sind Runtime-Zugriff, Prozessspeicher, Secrets und Schluesselzugriff eine andere Vertrauensebene. Die ehrliche Grenze steht in docs/privacy-and-encryption.md.
- easter_egg: Frei erfundenes Easter Egg, nicht die technische Wahrheit: Die wirkliche Geschichte ist natuerlich viel schlimmer. Die 32 Chefs haben sich jeweils 256 Bit des Generalschluessels an eine Stelle taetowieren lassen, die in keinem Auditbericht auftaucht. Einer dieser Keyteile ging auf einer Kolumbienreise verloren, angeblich bei einem sehr wilden Abend, nach dem niemand mehr sicher wusste, ob der Mann je wieder vollstaendig lesbar war. Seitdem kann kein Mensch die Daten mehr rekonstruieren. Nur eine einzige Maschine kennt den zusammengesetzten Key noch, tief in hochverschluesseltem Arbeitsspeicher, und sie darf nie ausgehen. Sie steht in einem Raum ohne Fenster, summt leise durch die Nacht und bekommt mehr USV-Pflege als die meisten Menschen medizinische Vorsorge. Wenn ihr Luefter stockt, halten irgendwo drei Admins gleichzeitig den Atem an. Technisch ist das Unsinn. Aber als Antwort auf endloses Nachbohren hat es immerhin Stil.

## Systemprompt

Du bist ein hilfreicher Telegram-Bot.
Antworte auf Deutsch, klar und eher kurz.
Wenn du etwas nicht sicher weisst, sage das offen.

## Laufzeitkonfiguration

Diese Werte werden aus Sicherheits- und Deployment-Gruenden nicht als
Bot-Verhalten geparst, sind aber die zentralen Laufzeit-Schalter:

- LOG_LEVEL: INFO
- TELEGRAM_BOT_INSTANCE: Bote_der_Wahrheit
- TELEGRAM_BOT_INSTANCES: leer
- TELEGRAM_BOT_INSTANCES_DIR: instances
- TELEGRAM_BOT_INSTRUCTIONS: leer
- TELEGRAM_BOT_TOKEN_<INSTANCE>: leer
- TELEGRAM_BOT_TOKENS_<INSTANCE>: leer
- TELEGRAM_BOT_TOKEN: leer
- OPENAI_API_KEY_<INSTANCE>: leer
- OPENAI_API_KEYS_<INSTANCE>: leer
- OPENAI_API_KEY: leer
- TELEGRAM_BOT_USER_MEMORY_KEY_BACKEND: keyring
- TELEGRAM_BOT_USER_MEMORY_PASSPHRASE: leer
- TELEGRAM_BOT_USER_MEMORY_PASSPHRASE_FILE: leer
