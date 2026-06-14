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

## Interne operatorgepflegte Hinweise

Interne operatorgepflegte Hinweise sind eine separate Vertrauensebene. Sie werden Usern nicht mit internem Dateinamen offengelegt und sind nicht Teil der oben beschriebenen strukturierten verschluesselten Memory-Dateien.

## Was geschuetzt ist

Reiner Dateizugriff sieht bei strukturierten Dateien Ciphertext. Interne operatorgepflegte Hinweise und Runtime-Zugriff sind eigene Vertrauensebenen. Wer Zugriff auf den laufenden Prozess, Secret Service, Passphrase oder Debugger hat, kann weiterhin Plaintext erreichen, weil der Bot Daten zum Arbeiten entschluesseln muss.
