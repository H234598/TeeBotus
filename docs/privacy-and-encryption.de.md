# Datenschutz und Verschluesselung

TeeBotus stellt von Telegram-Sender-Erinnerungen auf accountweite Erinnerungen um. Die fachliche Grenze ist jetzt die TeeBotus-Account-ID innerhalb einer Instanz.

## Account-ID und Kommunikationswege

- Die Account-ID ist ein 128 Zeichen langer SHA-512-Hexwert aus Zufallsbytes.
- Die Account-ID ist kein Passwort, wird aber nicht in Gruppenchats ausgegeben.
- Telegram-User-IDs, Signal-UUIDs, Signal-Nummern und spaetere Kanaele werden als Kommunikationswege eines Accounts gespeichert.
- Zum Verknuepfen eines neuen Kommunikationswegs braucht man Account-ID plus Account-Secret.

## Account-Secret

- Das Account-Secret wird bei `/register` erzeugt und nur einmal im Privatchat gezeigt.
- Das Klartext-Secret wird nicht gespeichert.
- Gespeichert wird nur ein HMAC-SHA512-Verifier.
- Der HMAC-Pepper kommt pro Instanz aus dem Secret Service via `secret-tool`.
- `/rotate_secret` invalidiert das alte Secret.

## Verschluesselte Dateien

Strukturierte Account-Dateien werden mit AES-256-GCM verschluesselt. Die Schluessel liegen instanzgebunden im Secret Service.

Identity- und Account-Mapping nutzen den separaten Zweck:

```text
account-identity-mapping-key
```

Strukturierte Account-Memory nutzt den separaten Zweck:

```text
account-structured-memory-key
```

Verschluesselte strukturierte Memory-Dateien:

- `User_Memory_Index.json`
- `User_Memory_Entries.jsonl`
- `OpenAI_State.json`

Auch Account-Index, Identity-Mapping, Secret-Verifier, Profile und Tombstones werden verschluesselt gespeichert.

## Klartext-Markdown

`User_Habbits_and_behave.md` bleibt absichtlich Klartext. Diese Datei ist eine manuell editierbare Markdown-Notiz. Sie wird bei Account-Merges zusammengefuehrt, aber nicht verschluesselt.

## Alte Daten

Alte `data/users/<telegram_sender_id>`-Memorys koennen in den neuen Account-Speicher migriert werden. Verschluesselte alte Memorys brauchen weiterhin den alten Keyring- oder Passphrase-Kontext. Wenn der alte Schluessel nicht lesbar ist, wird der Nutzer uebersprungen und der Legacy-Ordner bleibt erhalten.

## Was geschuetzt ist

Reiner Dateizugriff sieht bei strukturierten Dateien Ciphertext. Reiner Dateizugriff sieht aber weiterhin die Markdown-Notizen im Klartext. Wer Zugriff auf den laufenden Prozess, Secret Service, Passphrase oder Debugger hat, kann weiterhin Plaintext erreichen, weil der Bot Daten zum Arbeiten entschluesseln muss.
