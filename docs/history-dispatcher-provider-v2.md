# History-Dispatcher Provider-v2-Adapter

**Stand:** 30. Juli 2026  
**Schnitt:** `TB-HD-01-provider-v2-adapter-foundation`  
**Serververtrag:** `H234598/History-Dispatcher@01c791c252547c3766edfae97f2628a5c3cf6183`

## 1. Zweck

TeeBotus bleibt ein auswählbarer Telegram-Transportworker des zentralen
History-Dispatchers. Der History-Dispatcher besitzt Event, Route-Plan,
Target-/Recipient-Delivery, Claim, Lease, Attempt, Retry und Aggregation.
TeeBotus besitzt private Account-/Messenger-Routen und den konkreten Versand.

Der Adapter unterstützt genau:

```text
provider = teebotus
target = telegram
capability = history-dispatcher-telegram-v2
schema_version = 2
```

Ein Worker darf keine Delivery des Providers `history_dispatcher` claimen. Es
gibt keinen automatischen Cross-Provider-Fallback.

## 2. Operationen

```text
provider.v2.claim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

Der Unix-Socket-Client kann für diese Mutationen eine explizite Request-ID
übernehmen. Beim Replay wird exakt dieselbe Kombination aus Operation, Body und
Request-ID verwendet.

## 3. Claim

`claim_provider_v2` setzt Target, Provider und Capability intern fest. Die
Antwort wird fail-closed geprüft:

- Provider-API-Schema muss `2` sein;
- Target muss `telegram` sein;
- Provider muss `teebotus` sein;
- Capability und Binding müssen `history-dispatcher-telegram-v2` enthalten;
- Worker-ID muss dem anfragenden Worker entsprechen;
- Claimtoken muss formell gültig sein;
- Payload und Recipientlisten müssen die erwartete Struktur besitzen;
- doppelte Target- oder Recipientreferenzen werden abgewiesen.

Der Claimtoken wird nur im Speicher und in unmittelbar notwendigen
Folge-Requests verwendet.

## 4. Opaque Recipientrouten

TeeBotus löst private Admin-/Accountrouten weiterhin lokal auf. Gegenüber dem
History-Dispatcher erscheinen ausschließlich opaque Accountreferenzen. Rohe
Chat-IDs, Bot-Tokens oder Accountobjekte sind kein Teil des Providervertrags.

Bereits erfolgreiche Recipientrefs werden vom Store getrennt ausgewiesen und
bei späteren Versuchen nicht erneut gesendet.

## 5. Verschlüsselter Callback-Spool

Providercallbacks können Claimtokens enthalten. Dafür existiert ein eigener
`ProviderCallbackSpool`, getrennt vom bisherigen Legacy-`CallbackSpool`.

Eigenschaften:

- separater per-instance Secret-Purpose
  `history-dispatcher-provider-v2-callback-spool`;
- exakt 32 Byte Secret;
- AES-256-GCM mit zufälligem 96-Bit-Nonce;
- Instanzname und Formatmagic als Additional Authenticated Data;
- Verzeichnis `0700`, Dateien `0600`;
- atomare owner-only Anlage und Verzeichnis-fsync;
- maximal 256 KiB Klartext pro Callback;
- identische Event-ID darf nur identischen entschlüsselten Inhalt besitzen;
- beschädigte, fremde oder nicht authentifizierbare Dateien werden nicht
  ausgeführt;
- Replay verwendet exakt Operation, Body und Request-ID;
- erfolgreicher Replay löscht und synchronisiert die Spooldatei.

Damit liegt ein Claimtoken niemals im Klartext auf Platte.

## 6. Bewusste Schnittgrenze

Dieser PR aktiviert den Provider-v2-Pfad noch nicht in
`dispatch_codex_history_outbox`. Der bestehende `legacy`/`shadow`/`bridge`-
Betrieb bleibt unverändert, bis der folgende Cutover-Schnitt zusätzlich
beweist:

1. private Route vor dem Claim;
2. dynamische Recipientregistrierung;
3. Leaseverlängerung während langer Sends;
4. monotone Recipientresultate;
5. kein erneuter Versand erfolgreicher Empfänger;
6. Crash-after-Accept-Reconciliation;
7. Callback-Spool-Rebind nach Claimablauf;
8. Rate-Limit-/Hänger-/Partial-Fault-Korpus;
9. kein automatischer Rückfall auf globales `dispatch.claim`.

## 7. Gemeinsamer Fixture-Korpus

```text
tests/fixtures/provider-v2/contract.json
```

Der Inhalt ist semantisch identisch mit dem Fixture im History-Dispatcher und
enthält ausschließlich künstliche opaque Referenzen.
