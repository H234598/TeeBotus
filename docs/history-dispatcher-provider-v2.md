# History-Dispatcher Provider-v2-Cutover

**Stand:** 30. Juli 2026  
**Schnitte:** `TB-HD-01-provider-v2-adapter-foundation`, `TB-HD-02-provider-v2-cutover`  
**Serververtrag:** `H234598/History-Dispatcher@0934e85e53ae03d97df57ef494cd1aec7d141ef3`  
**Provider-Schema:** `2`

## 1. Zweck und Eigentümerschaft

TeeBotus ist ein explizit auswählbarer Telegram-Transportworker des zentralen
History-Dispatchers.

Der History-Dispatcher besitzt:

- Event und verschlüsselte Payload;
- Route-Plan und unveränderliche Providerbindung;
- Target- und Recipient-Deliveries;
- Claim, Lease und Attempt;
- Idempotenz, Retry, Backoff und Quarantäne;
- Aggregation und Reconciliation.

TeeBotus besitzt:

- private Account- und Messenger-Routen;
- die konkrete Telegramzustellung;
- lokale Auflösung autorisierter Admin-Accounts;
- den verschlüsselten Callback-Spool.

Der Adapter unterstützt genau:

```text
provider = teebotus
target = telegram
capability = history-dispatcher-telegram-v2
schema_version = 2
```

Ein TeeBotus-Worker kann keine Delivery des Providers `history_dispatcher`
claimen. Es gibt keinen automatischen Cross-Provider-, Bridge- oder
Legacy-Fallback.

## 2. Aktivierung

Der produktive, explizite Modus lautet:

```bash
TEEBOTUS_HISTORY_DISPATCHER_MODE=provider_v2
```

Die bestehenden Modi bleiben unverändert:

```text
legacy
shadow
bridge
provider_v2
```

Unbekannte Werte fallen weiterhin auf `legacy`. Ein Fehler innerhalb von
`provider_v2` aktiviert jedoch keinen anderen Modus; der Lauf schlägt
fail-closed fehl oder bleibt durch den Callback-Spool blockiert.

## 3. Provider-v2-Operationen

```text
provider.v2.claim
provider.v2.reclaim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

Der Unix-Socket-Client übernimmt für diese Mutationen explizite Request-IDs.
Beim Replay wird exakt dieselbe Kombination aus Operation, Body und Request-ID
verwendet, bis ein gezielter Reclaim einen neuen Attempt und damit eine neue
phasen- und Attempt-gebundene Request-ID erzeugt.

## 4. Fail-closed Batchworker

Vor einem neuen Claim führt der Worker folgende Reihenfolge aus:

1. verschlüsselten Provider-Callback-Spool flushen;
2. bei unresolved Callback alle neuen Claims und Sends blockieren;
3. aktuell routbare private Recipientrefs lokal bestimmen;
4. ohne routbare Empfänger keinen Claim anfordern;
5. Workerheartbeat `polling` melden;
6. provider- und capabilitygebunden claimen;
7. opaque Recipientrefs unter dem Claim registrieren;
8. bereits erfolgreiche oder `possible_duplicate`-Empfänger ausschließen;
9. Lease vor jedem noch offenen Transport verlängern;
10. Telegramtransport ausführen;
11. Recipientresultate vor der Targetcompletion persistieren;
12. gespultes Recipientresultat blockiert Completion und Batch;
13. Targetcompletion melden;
14. gespulte Completion blockiert den Batch;
15. abschließenden Heartbeat melden.

Der Worker verwendet stabile, phasen-, Target- und Attempt-gebundene
Request-IDs. Ein Transportfehler wird in ein begrenztes Recipientresultat
übersetzt und beendet nicht unkontrolliert den Workerprozess.

## 5. Claimprüfung

`claim_provider_v2` setzt Target, Provider und Capability intern fest. Die
Antwort wird fail-closed geprüft:

- Provider-API-Schema muss `2` sein;
- Target muss `telegram` sein;
- Provider muss `teebotus` sein;
- Capability und Binding müssen `history-dispatcher-telegram-v2` enthalten;
- Worker-ID muss dem anfragenden Worker entsprechen;
- Target-Deliveries dürfen nicht doppelt vorkommen;
- Claimtoken muss formell gültig sein;
- Payload und Recipientlisten müssen die erwartete Struktur besitzen;
- doppelte Recipientrefs werden abgewiesen.

Der Claimtoken wird nur im Speicher oder AES-GCM-verschlüsselt im
Provider-Callback-Spool gehalten.

## 6. Opaque Recipientrouten

TeeBotus löst private Admin-/Accountrouten lokal auf. Gegenüber dem
History-Dispatcher erscheinen ausschließlich opaque Accountreferenzen. Rohe
Chat-IDs, Bot-Tokens und private Accountobjekte sind kein Teil des
Providervertrags.

Bereits erfolgreiche Recipientrefs werden vom zentralen Store getrennt
zurückgegeben und nicht erneut gesendet. Der Zustand `possible_duplicate`
autorisiert ebenfalls keinen neuen Send und bleibt bis zur Reconciliation
blockierend.

Telegram-Message-IDs werden vor der zentralen Persistenz in einen stabilen
opaque `message_ref_key` überführt.

## 7. Verschlüsselter Callback-Spool

Provider-Callbacks können Claimtokens enthalten. Dafür existiert ein eigener
`ProviderCallbackSpool`, getrennt vom Legacy-`CallbackSpool`.

Eigenschaften:

- separater per-instance Secret-Purpose
  `history-dispatcher-provider-v2-callback-spool`;
- exakt 32 Byte Secret;
- AES-256-GCM mit zufälligem 96-Bit-Nonce;
- Instanzname und Formatmagic als Additional Authenticated Data;
- Verzeichnis `0700`, Dateien `0600`;
- atomare owner-only Anlage und Verzeichnis-fsync;
- maximal 256 KiB Klartext pro Callback;
- identische Event-ID akzeptiert nur identischen entschlüsselten Inhalt;
- beschädigte, fremde oder nicht authentifizierbare Dateien werden nicht
  ausgeführt;
- erfolgreicher Replay löscht und synchronisiert die Spooldatei.

Damit liegt ein Claimtoken niemals im Klartext auf Platte.

## 8. Callback-Rebind nach Leaseablauf

Nach einem externen Telegram-Accept kann der zugehörige Recipient- oder
Completioncallback länger als die Claim-Lease im verschlüsselten Spool liegen.
Der alte Claimtoken ist dann korrekt ungültig.

Jedes spoolbare Provider-v2-Envelope enthält deshalb zusätzlich:

```text
target_delivery_id
provider_id = teebotus
worker_id
capability_version = history-dispatcher-telegram-v2
previous_attempt_no
```

Der Flush versucht zunächst immer den exakten ursprünglichen Callback. Nur bei
eindeutigen Claimablauf-Fehlern wird `provider.v2.reclaim` verwendet:

```text
claim has expired
not actively claimed
claim maximum lifetime has elapsed
```

Andere Transport-, Berechtigungs- oder Protokollfehler lösen keinen Reclaim aus
und lassen den Spool unverändert blockierend bestehen.

Ein erfolgreicher Reclaim muss:

- dieselbe Target-Delivery zurückgeben;
- Provider `teebotus` und passende Capability besitzen;
- exakt den nächsten Attempt liefern;
- `reconciliation_only=true` enthalten;
- einen neuen One-shot-Claimtoken liefern.

Anschließend wird die bestehende Spooldatei atomar und erneut verschlüsselt auf
folgenden Stand umgeschrieben:

- neuer Claimtoken;
- neue Attemptnummer;
- neue attemptgebundene Callback-Request-ID;
- unveränderte ursprüngliche Callbackoperation und Fachdaten.

Danach wird ausschließlich der ursprüngliche Recipient- oder
Completioncallback replayt. Ein `reconciliation_only`-Claim wird niemals an den
Sendadapter übergeben und autorisiert keinen neuen Telegram-Send.

Scheitert der Callback nach erfolgreichem Rebind erneut, bleibt das bereits auf
den neuen Attempt umgeschriebene verschlüsselte Envelope bestehen. Ein späterer
Flush setzt damit am aktuellen Attempt fort, statt den alten Token erneut zu
verwenden.

## 9. Dry Run und Legacykompatibilität

Ein Dry Run des Codex-History-Pfads:

- fordert keinen Providerclaim an;
- berührt keinen Claimtoken;
- sendet keine Telegramnachricht;
- zeigt nur geplante beziehungsweise gespiegelte Zustände.

Die Modi `legacy`, `shadow` und `bridge` behalten ihre bisherigen Operationen
und Semantik. Der neue Provider-v2-Worker nutzt nicht das globale
`dispatch.claim` und fällt bei Fehlern nicht darauf zurück.

## 10. Gemeinsamer Fixture- und Fault-Korpus

```text
tests/fixtures/provider-v2/contract.json
```

Der Fixture ist semantisch identisch zum History-Dispatcher-Vertrag und enthält
unter anderem `provider.v2.reclaim`. Er verwendet ausschließlich künstliche
opaque Referenzen.

Abgedeckte Fehlerfälle:

- kein Claim ohne routbare private Route;
- Provider-/Capability-/Binding-Mismatch;
- erfolgreicher Empfänger wird nicht erneut gesendet;
- `possible_duplicate` wird nicht erneut gesendet;
- unresolved Callback-Spool blockiert neue Sends;
- gespulter Recipientcallback verhindert Completion;
- gespulte Completion blockiert den Batch;
- Claimablauf nach externem Accept;
- gezielter Reclaim derselben Target-Delivery;
- atomarer verschlüsselter Rebind auf neuen Token und Attempt;
- non-expiry Fehler lösen keinen Reclaim aus;
- leerer oder stale Reclaim lässt den ursprünglichen Callback blockiert;
- Worker übergibt die Attemptnummer an alle spoolbaren Callbacks;
- kein Claimtoken im Klartext auf Platte.

## 11. Bewusste Schnittgrenze

Dieser TeeBotus-Cutover implementiert nicht den nativen Telegramworker des
History-Dispatchers und verwaltet keine History-Dispatcher-Bot-Credentials.
TeeBotus bleibt nur einer von zwei explizit auswählbaren Providern.

Der produktive Config-v2-Writer, der Cinnamon-Settingsschalter und der native
History-Dispatcher-Telegramworker folgen in getrennten Schnitten. Der
Provider-v2-Cutover darf erst nach vollständigen Core-, Audit-, Benchmark-,
Plan2-, qlty- und CodeRabbit-Gates gemergt werden.
