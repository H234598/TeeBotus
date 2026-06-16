# Privacy and Encryption

TeeBotus is moving from Telegram-sender memory to account-scoped memory. The stable privacy boundary is now the TeeBotus account ID inside one instance.

## Account Identity

- A TeeBotus account ID is a 128-character SHA-512 hex token generated from random bytes.
- The account ID is not a password, but the bot does not print it in group chats.
- Telegram users, Signal UUIDs, Signal numbers, and future channel identities are stored as communication identities linked to an account.
- Account linking requires account ID plus account secret.

## Account Secret

- The account secret is generated once during registration and shown only in private chat.
- The plaintext secret is never stored.
- TeeBotus stores an HMAC-SHA512 verifier derived from the secret and a per-instance pepper.
- The pepper comes from Secret Service via `secret-tool`.
- Secret rotation invalidates the previous secret.

## Encrypted Files

The account store encrypts structured files with AES-256-GCM envelopes and instance-scoped Secret Service keys.

Identity and account metadata use the separate purpose:

```text
account-identity-mapping-key
```

Structured account memory uses the separate purpose:

```text
account-structured-memory-key
```

Encrypted structured memory files:

- `User_Memory_Index.json`
- `User_Memory_Entries.jsonl`
- `LLM_State.json` (`OpenAI_State.json` is migrated as a legacy name)
- `Agent_State.json`
- `Proactive_Outbox.jsonl`
- `Proactive_Audit.jsonl`

Encrypted account files include identity mappings, account index, account secrets/verifiers, account profiles, and tombstones.

## Plaintext Markdown

Operator-maintained internal notes are a separate trust level. They are not exposed to users by internal filename and are not part of the structured encrypted memory files described above.

## What This Protects

Disk-only access sees ciphertext for encrypted structured files. Disk-only access still sees plaintext Markdown notes. Runtime access with process, Secret Service, or debugger access can still reach plaintext because the bot must decrypt data to operate.

## Short User Reply

Structured user memory is encrypted at rest. In the account runtime, structured account memory is encrypted with instance-scoped Secret Service keys. The account secret is not stored, only an HMAC verifier is. Operator-maintained internal notes are a separate trust level. The running bot can still decrypt what it needs while processing messages.
