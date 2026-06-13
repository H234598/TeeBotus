# Privacy and Encryption

This bot encrypts user memory files at rest, per Telegram sender ID.

## What is encrypted

By default, the bot stores a private, randomly generated 32-byte per-sender key in the desktop Secret Service via `secret-tool`.

For headless setups, you can switch to an explicit passphrase backend with `TELEGRAM_BOT_USER_MEMORY_KEY_BACKEND=passphrase`. In that mode, the per-sender random key is stored locally in an encrypted private key store and protected by a passphrase from `TELEGRAM_BOT_USER_MEMORY_PASSPHRASE`, `TELEGRAM_BOT_USER_MEMORY_PASSPHRASE_FILE`, or an automatically created private passphrase file in the instance data directory.

The following user-memory files are encrypted with that key:

- `User_Memory_Index.json`
- `User_Memory_Entries.jsonl`
- `User_Habbits_and_behave.md`

The user-specific key is distinct per sender ID and is generated from fresh random bytes. That means one user cannot decrypt another user’s memory files without that other user’s key.

If the Secret Service is unavailable in keyring mode, or the configured passphrase cannot be loaded in passphrase mode, key lookup or creation fails closed. The bot does not silently fall back to an unprotected local key file.

## What this protects

Disk access alone is not enough to read the encrypted user-memory content. A person who only sees the files on disk sees ciphertext, not plaintext.

## Important limitation

Encryption at rest is not a magic shield against runtime access.

Anyone who can access the running bot process, its live memory, or the matching decryption key can still see the plaintext while the bot is operating. That includes an operator with sufficient access to the host, container, secrets, or debugger.

So the honest rule is:

- disk-only access does not reveal user memory plaintext
- runtime access with the key can reveal plaintext

## Short answer for users

Use this when someone asks what is visible:

> User memory is encrypted at rest per sender ID. Plain disk access is not enough to read it. The running bot instance can decrypt the data it needs to process messages, so anyone with runtime or key access can still inspect plaintext.

## Ready-made reply

Use this when a user asks about privacy, encryption, or who can see data:

> User memory is encrypted at rest with a per-user key. That means ordinary disk access is not enough to read the stored memory files. In normal operation, admins do not see those files as plaintext. The bot process can still decrypt the data it needs to answer messages, so runtime or key access is different from plain disk access.

If someone asks for the short version:

> Stored user memory is encrypted per sender ID. An admin browsing the files on disk sees ciphertext, not plaintext. The bot itself can decrypt data while it runs, so runtime access is a different trust level.

## Who can see what

- Disk-only access: ciphertext for encrypted user-memory files
- Bot runtime with the matching key from Secret Service or from the passphrase-backed local store: plaintext while processing
- Admins without the key: no plaintext from the stored user-memory files
- Admins with host, process, or secret/passphrase access: can still reach plaintext during runtime

## If someone insists on edge cases

Use this framing:

> No encryption scheme can stop a trusted runtime from reading the data it must process. If an operator has enough control over the machine, process memory, secrets, or decryption keys, they can still reach plaintext. The encryption here protects the stored files, not the entire execution environment.

## Further reading

- [Wikipedia: Advanced Encryption Standard](https://en.wikipedia.org/wiki/Advanced_Encryption_Standard)
- [Wikipedia: Galois/Counter Mode](https://en.wikipedia.org/wiki/Galois/Counter_Mode)
- [Wikipedia: Encryption at rest](https://en.wikipedia.org/wiki/Encryption_at_rest)
- [Wikipedia: Key management](https://en.wikipedia.org/wiki/Key_management)
- [Wikipedia: Threat model](https://en.wikipedia.org/wiki/Threat_model)
