# TeeBotus Plan v3.3 — HF-Pool Safe Rollout, Minimalertrag, Qdrant, Memory, Haystack und Pydantic AI

**Ziel:** Den aktuellen TeeBotus-Stand, Plan2 und das Deep Research zu Hugging Face Inference Providers zu einem neuen, aktualisierten Umsetzungsplan zusammenführen.

**Leitentscheidung:** `hf_pool` wird ein eigenes Paket. LiteLLM bleibt generischer Provider-Adapter/Gateway-Schicht. TeeBotus bekommt zusätzlich einen eigenen Hugging-Face-Pool-Provider, der mehrere HF-Router-Ziele, HF-Tokens, HF-Inference-Endpoints, Health, Cooldowns, Usage und Purpose-Routing verwaltet.

**Wichtig:** Keine Big-Bang-Migration. TeeBotus bleibt Kernsystem. Frameworks und Provider werden als austauschbare Organe eingebaut.

**v3.3-Zusatz:** Qdrant wird gemeinsamer semantischer Index für Bibliothekar und Usermemory; AccountStore bleibt Wahrheit; Haystack bleibt optionales Pipeline-Backend; Pydantic AI wird als typisierte Decision-Schicht eingeplant; `hf_pool` ist optional, lazy und non-fatal, bis Doctor mindestens ein gesundes Target meldet; zusätzlich ist ein Minimalertrag/MVP-Pfad definiert, damit die Umsetzung sofort nutzbar und rollbackfähig bleibt.

## Implementierungsstand

Stand: 2026-06-19

Quelle:

- `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/Plan3.md` ist in `docs/Plan3.md` integriert.
- Download-SHA256: `86a7832047b1de63c50fb5776d7e98f3c54d277054cf518267e03be000fb8553`
- Der Dokumentkoerper folgt dem aktuellen Download-Stand; dieser Kopf fuehrt den Repo-Status analog zu `docs/Codex_Outbox_History_Plan.md`.

Umgesetzt:

- Der Plan liegt versioniert unter `docs/` und enthaelt die v3.1-, v3.2- und v3.3-Ergaenzungen.
- Der Safe-Rollout-/Minimalertrag-Pfad fuer `hf_pool` ist als priorisierte Umsetzungsreihenfolge dokumentiert.
- Qdrant, Embedding-Schicht, MemorySearchService, Bibliothekar-Qdrant, Pydantic-AI-Decisions und Benchmarkauftraege sind als getrennte Arbeitspakete beschrieben.

Offen:

- Der Code-Umsetzungsstand der einzelnen Plan3-Arbeitspakete muss pro Paket gegen Tests, Runtime-Status und Benchmarks gepflegt werden.
- Wenn Plan3 spaeter fortgeschrieben wird, soll dieser Kopf wie beim Codex-Outbox-Plan den aktuellen Stand sichtbar halten.

---

## 1. Kurzurteil

Plan2 ist als Grundstruktur weiterhin brauchbar, aber mehrere Punkte sind durch den aktuellen GitHub-Stand und das Deep Research überholt.

### Schon im Repo vorhanden

```text
- TeeBotus/llm/base.py mit LLMResponse, LLMVoice, LLMImage, BaseLLMClient
- TeeBotus/llm/litellm_provider.py als text-only LiteLLM Adapter
- TeeBotus/llm/profiles.py mit Profilen und purpose-basiertem Routing
- TeeBotus/runtime/llm_factory.py mit build_runtime_text_llm_client()
- config/llm_profiles.yaml und config/llm_routing.yaml
- pyproject.toml mit pinned Extras
- TeeBotus/runtime/bibliothekar_service.py mit Local- und Haystack-Backend
```

### Plan2 muss geändert werden

```text
Nicht mehr:
  "LLM-Router erst neu bauen"

Sondern:
  vorhandenen Router härten und um hf_pool erweitern

Nicht mehr:
  "Haystack-Bibliothekar als Neubau"

Sondern:
  bestehenden BibliothekarService behalten,
  LocalBackend weiter nutzen,
  HaystackBackend optional,
  LlamaIndexBackend als Doc-Chat-Experiment ergänzen

Neu:
  hf_pool als eigenes Paket
  separate embedding-Schicht
  QdrantMemoryIndex als semantischer Index für Usermemory
  Benchmark- und Evaluation-Schicht früh einbauen
```

---

## 2. Architekturentscheidung v3

### 2.1 Rollen

| Komponente | Rolle |
|---|---|
| `TeeBotusEngine` | Bot-Kern, Account-Flows, Memory-Kontext, Commands, Events |
| `TeeBotus.llm` | Providerneutrale LLM-Interfaces und Adapter |
| `LiteLLMTextClient` | generischer Textadapter für OpenAI-kompatible/unterstützte Provider |
| `hf_pool` | eigener Hugging-Face-Pool-Provider mit Targets, Health, Scheduler, Metrics |
| `OpenAIClient` | Spezialclient für Responses, Images, TTS, Transcription |
| `BibliothekarService` | zentrale Bibliothekar-Schnittstelle |
| `LocalBibliothekarBackend` | bestehender lokaler JSONL/Index-Bibliothekar |
| `HaystackBibliothekarBackend` | optionales Pipeline-/Qdrant-Backend |
| `LlamaIndexBackend` | optionales Doc-Chat-/Q&A-Backend für einige Hundert Bücher |
| `QdrantMemoryIndex` | semantischer Suchindex für Usermemory, nicht Wahrheitsspeicher |
| `AccountStore` | Wahrheitsspeicher für Account, Identitäten, verschlüsselte Memories |
| `Pydantic AI` | strukturierte Entscheidungen |
| `LangGraph` | lange kontrollierte Workflows |
| `CrewAI` | Spezial-Agenten / Expeditionsteams |
| `MCP/FastMCP` | spätere Tool-Schicht, read-only zuerst |

### 2.2 High-Level Zielbild

```text
Messenger
  ├─ Telegram
  ├─ Signal
  └─ Matrix
        ↓
IncomingEvent
        ↓
TeeBotusEngine
  ├─ AccountStore
  ├─ RuntimeState
  ├─ WorkingMemory
  ├─ MemorySearchService
  │    ├─ Keyword/Metadata Search
  │    └─ QdrantMemoryIndex
  ├─ BibliothekarService
  │    ├─ LocalBackend
  │    ├─ LlamaIndexBackend
  │    └─ HaystackBackend
  ├─ Pydantic Decision Layer
  ├─ LangGraph Workflows
  ├─ CrewAI Spezialagenten
  └─ LLM Router
        ├─ OpenAIClient
        ├─ LiteLLMTextClient
        └─ hf_pool
              ├─ HF Router /v1/chat/completions
              ├─ HF Inference Providers
              ├─ HF Dedicated Endpoints
              └─ HF Metrics / Cooldown / Scheduling
```

---

## 3. HF-Pool-Strategie

### 3.1 Warum eigener Provider?

Ein einzelnes `provider: litellm`, `model: huggingface/...` reicht für einfache HF-Aufrufe. Für TeeBotus wollen wir aber mehr:

```text
- mehrere Hugging-Face-Tokens
- mehrere Inference-Provider-Ziele
- ggf. Dedicated Inference Endpoints
- Modelle je Zweck/Bucket
- dynamische Auswahl nach Preis, Latenz, Kontext, Tool-/Structured-Support
- Cooldown nach 429/5xx/Timeout
- Usage- und Qualitätsdaten
- Healthchecks
- klare Trennung zwischen Chat, Embeddings, Reranking
```

Darum wird `hf_pool` ein eigenes Paket.

### 3.2 Paketstruktur

```text
TeeBotus/llm/hf_pool/
  __init__.py
  config.py
  targets.py
  provider.py
  scheduler.py
  state.py
  health.py
  executor.py
  models_feed.py
  errors.py
  metrics.py
  redaction.py
```

### 3.3 Aufgaben der Module

```text
config.py
  lädt config/hf_pool.yaml
  validiert Pools, Targets, Zwecke, Tokens, Model IDs

targets.py
  HFPoolTarget, HFPoolKind, TargetCapabilities

provider.py
  HFPoolProvider(BaseLLMClient)
  create_reply() → LLMResponse

scheduler.py
  purpose_filter
  health_filter
  weighted_round_robin
  cost_first / latency_first später
  fallback-chain

state.py
  SQLite-State:
    cooldowns
    failures
    successes
    avg_latency_ms
    usage events

health.py
  runtime status / doctor checks
  optional /v1/models validation

executor.py
  OpenAI-compatible HTTP calls an HF Router oder Endpoint
  timeout
  streaming später
  response normalization

models_feed.py
  optionaler Import von /v1/models Metadaten:
    context_length
    pricing
    supports_tools
    supports_structured_output
    latency
    throughput

errors.py
  HFPoolError
  HFPoolConfigError
  HFPoolTargetUnavailable
  HFPoolRateLimited

metrics.py
  usage event
  latency
  tokens
  provider/model/target

redaction.py
  hf_ Token, Bearer Token, URLs, Secrets entfernen
```

---

---

# Ergänzung v3.2 — HF-Pool Safe Rollout / Non-Fatal Provider

Diese Ergänzung ist eine harte Betriebsinvariante für `hf_pool`.

## 1. Problem

`hf_pool` wird groß und mächtig, aber zu Beginn werden nicht alle Hugging-Face-Tokens, Inference-Provider-Ziele oder Dedicated Endpoints vorhanden sein.

Darum darf TeeBotus nicht so gebaut werden, dass fehlende Hugging-Face-Konfigurationen den Botstart brechen.

```text
Falsch:
  config/hf_pool.yaml fehlt
  → TeeBotus startet nicht

Richtig:
  config/hf_pool.yaml fehlt
  → hf_pool status=not_configured
  → Bot startet weiter
```

```text
Falsch:
  HF_TOKEN_MAIN fehlt
  → Runtime bricht ab

Richtig:
  HF_TOKEN_MAIN fehlt
  → target status=missing_key
  → hf_pool unavailable
  → Fallback oder freundlicher LLM-Fehler
  → Bot lebt
```

## 2. Harte Regeln

```text
Implement hf_pool as optional, lazy, non-fatal provider.
Missing HF configuration must degrade to unavailable runtime status, not break TeeBotus startup.
Do not make hf_pool the default route until doctor reports at least one healthy target.
```

Zusätzlich:

```text
- hf_pool darf beim Import keine HF-Library hart verlangen.
- config/hf_pool.yaml darf fehlen.
- HF_TOKEN_* darf fehlen.
- ein Pool darf leer oder disabled sein.
- ein Target darf missing_key, disabled, cooldown oder unhealthy sein.
- fehlende HF-Instanzen sind Runtime-Status, kein Startfehler.
- Standardtests nutzen MockExecutor.
- Live-HF-Tests laufen nur mit explizitem Flag.
```

## 3. Lazy Imports

Nicht:

```python
from huggingface_hub import InferenceClient
```

auf Modulebene.

Sondern:

```python
def _import_hf_client():
    try:
        from huggingface_hub import InferenceClient
    except ImportError as exc:
        raise HFPoolUnavailable("huggingface_hub not installed") from exc
    return InferenceClient
```

Oder für OpenAI-kompatible HTTP-Aufrufe zunächst nur stdlib/urllib oder vorhandene HTTP-Schicht verwenden.

## 4. Safe Default

`hf_pool` wird anfangs nicht globaler Default.

### Phase 1: sicherer Merge

```yaml
default_profile: openai_premium  # oder ein bereits funktionierender bestehender Provider

purposes:
  structured_decision:
    profile: hf_pool_structured
    fallback: groq_fast

  normal_chat:
    profile: openai_premium
    fallback: null
```

Oder noch vorsichtiger:

```yaml
default_profile: openai_premium

purposes:
  structured_decision:
    profile: groq_fast
    fallback: null
```

`hf_pool` wird dann nur über Doctor/Live-Test geprüft.

### Phase 2: gezielte Testinstanz

```yaml
default_profile: openai_premium

purposes:
  structured_decision:
    profile: hf_pool_structured
    fallback: groq_fast

  bibliothekar_answer:
    profile: hf_pool_bibliothekar
    fallback: openai_premium
```

### Phase 3: nach Doctor grün

Erst wenn mindestens ein Target gesund ist:

```yaml
default_profile: hf_pool_default

purposes:
  normal_chat:
    profile: hf_pool_default
    fallback: gemini_flash
```

## 5. Doctor / Runtime-Status

Neue Statuszeilen:

```text
hf_pool=default status=not_configured error=config/hf_pool.yaml missing
hf_pool=default status=disabled
hf_pool=default targets=0 healthy=0 unavailable=0 cooldown=0
hf_pool=default target=qwen_4b_structured status=missing_key env=HF_TOKEN_MAIN
hf_pool=default target=gemma_4_quality status=cooldown until=2026-06-16T12:00:00Z reason=429
hf_pool=default target=qwen_9b_budget status=healthy model=Qwen/Qwen3.5-9B latency_ms=440
llm_route=structured_decision profile=hf_pool_structured status=unavailable fallback=groq_fast
llm_route=normal_chat profile=openai_premium status=configured
```

Für Qdrant analog:

```text
qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search
memory_index=Depressionsbot backend=keyword status=ready semantic=unavailable
bibliothekar=Depressionsbot backend=local status=ready qdrant=unavailable
account_crypto=Depressionsbot status=ok mapping=present memory=present pepper=present keyring=ok
account_memory=Depressionsbot/<account_id> status=ok
account_identity=Depressionsbot status=ok identity_warnings=0 runtime_slots=signal:1,telegram:1 identities=signal:1,telegram:1
```

## 6. Verhalten bei fehlendem hf_pool

Wenn `provider=hf_pool` angefordert wird:

```text
1. Pool config laden.
2. Wenn config fehlt:
   HFPoolUnavailable("not_configured")

3. Wenn Pool disabled:
   HFPoolUnavailable("disabled")

4. Wenn keine Targets healthy:
   HFPoolUnavailable("no_healthy_targets")

5. LLM-Router prüft:
   - fallback erlaubt?
       ja → fallback nutzen
       nein → freundliche Fehlermeldung
   - Botprozess bleibt aktiv.
```

Freundliche Fehlermeldung:

```text
Ich kann das konfigurierte Hugging-Face-Modell gerade nicht erreichen. Ich antworte weiter, sobald ein Fallback oder ein gesunder HF-Target verfügbar ist.
```

Keine Secrets ausgeben.

## 7. Tests

Pflichttests:

```text
tests/test_hf_pool_nonfatal.py
tests/test_hf_pool_doctor.py
tests/test_hf_pool_missing_config.py
tests/test_hf_pool_missing_key.py
tests/test_hf_pool_fallback_routing.py
```

Testfälle:

```text
- config/hf_pool.yaml fehlt → Bot-/Router-Import geht weiter.
- Pool disabled → unavailable status.
- Target ohne Key → missing_key status.
- alle Targets unhealthy → no_healthy_targets.
- fallback erlaubt → fallback client wird genutzt.
- fallback nicht erlaubt → LLMAPIError, aber kein Runtime-Startabbruch.
- Runtime-Status redacted Secrets.
- Live-Tests standardmäßig skipped.
```

## 8. Live-Tests nur explizit

```bash
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_hf_pool_live.py
```

Optionaler Doctor:

```bash
python3 -m TeeBotus.llm.hf_pool.doctor
python3 -m TeeBotus.llm.hf_pool.doctor --live
```

Ohne `--live`:

```text
- Config validieren
- Env-Keys vorhanden?
- Targets syntaktisch korrekt?
- Pool enabled?
- Keine Netzaufrufe
```

Mit `--live`:

```text
- /v1/models prüfen
- Testcompletion mit kleinem Prompt
- Latenz messen
- Status speichern
```

## 9. Codex-Auftrag für Safe Rollout

```text
Implement hf_pool as optional, lazy, non-fatal provider.

Requirements:
- Missing config/hf_pool.yaml must not break TeeBotus startup.
- Missing HF_TOKEN_* must mark targets as missing_key.
- No target healthy must mark pool unavailable.
- hf_pool must not be made default_profile in the first merge.
- Standard tests must use MockExecutor only.
- Live HF tests must require TEEBOTUS_LIVE_HF=1.
- Runtime status must show hf_pool health without leaking secrets.
- If provider=hf_pool is requested and unavailable:
  - use fallback if explicitly allowed;
  - otherwise return a controlled LLMAPIError;
  - never abort the whole bot runtime.
```

## 10. Aktualisierte Reihenfolge

```text
Phase 1:
  hf_pool Paket + MockExecutor + nonfatal behavior

Phase 2:
  Doctor/Runtime-Status für hf_pool

Phase 3:
  Routerintegration, aber hf_pool nicht default

Phase 4:
  Live-HF-Executor hinter Flag

Phase 5:
  structured_decision testweise über hf_pool

Phase 6:
  bibliothekar_answer testweise über hf_pool

Phase 7:
  normal_chat nur für Testinstanz über hf_pool

Phase 8:
  hf_pool als default nur nach Doctor grün
```

## 11. Definition of Done für Safe Rollout

```text
- TeeBotus startet ohne config/hf_pool.yaml.
- TeeBotus startet ohne HF_TOKEN_*.
- Runtime-Status zeigt hf_pool unavailable statt Crash.
- hf_pool ist nicht globaler Default beim ersten Merge.
- Fallbacks greifen nur explizit.
- Kein Secret-Leak in Logs, Exceptions oder Runtime-Status.
- Mocktests decken missing_config, missing_key, no_healthy_targets und fallback ab.
- Live-HF-Tests sind standardmäßig aus.
```


---

# Ergänzung v3.3 — Minimalertrag / MVP-Pfad

Diese Ergänzung definiert den kleinsten sinnvollen Ertrag aus der Umsetzung, ohne dass TeeBotus durch fehlende Hugging-Face-Instanzen, fehlendes Qdrant oder fehlende optionale Frameworks unbenutzbar wird.

## 1. Ziel

Der erste produktive Nutzen soll nicht sein:

```text
Alles ist fertig:
  hf_pool
  Qdrant
  Bibliothekar-Qdrant
  Usermemory-Qdrant
  Pydantic AI
  LlamaIndex
  Haystack
  LangGraph
  CrewAI
```

Sondern:

```text
Kleinstes nützliches Ergebnis:
  TeeBotus startet stabil.
  hf_pool ist sichtbar, testbar und non-fatal.
  bestehende Provider laufen weiter.
  Runtime-Status zeigt, was fehlt.
  Mocktests beweisen das Verhalten.
```

Der Minimalertrag ist also ein stabiler technischer Sockel, nicht sofort die perfekte Modelllandschaft.

## 2. Minimalertrag Stufe 1 — hf_pool sichtbar, aber nicht aktiv

### Ergebnis

```text
- TeeBotus/llm/hf_pool existiert als Paket.
- hf_pool kann konfiguriert werden.
- hf_pool hat MockExecutor.
- hf_pool hat Doctor/Status.
- hf_pool bricht den Botstart nicht.
- hf_pool ist nicht default_profile.
```

### Noch nicht enthalten

```text
- keine echten HF-Calls
- kein Live-Routing
- kein Qdrant-Memory
- kein Bibliothekar-Qdrant
- kein Pydantic-AI-Livebetrieb
```

### Akzeptanz

```bash
python3 -m TeeBotus --version
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m pytest -q tests/test_hf_pool_config.py tests/test_hf_pool_nonfatal.py tests/test_hf_pool_doctor.py
```

### Nutzen

```text
- Wir wissen, dass der neue Provider sauber in TeeBotus passt.
- Fehlende HF-Config ist sichtbar.
- Fehlende HF-Tokens sind sichtbar.
- Botstart bleibt stabil.
```

## 3. Minimalertrag Stufe 2 — hf_pool mit einem Live-Target testbar

### Ergebnis

```text
- ein HF-Target aus config/hf_pool.yaml kann live getestet werden
- Live-Test nur mit Flag
- Usage/Latency wird erfasst
- Fehler erzeugen Cooldown statt Crash
```

### Akzeptanz

```bash
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_hf_pool_live.py
python3 -m TeeBotus.llm.hf_pool.doctor --live
```

### Routing

Noch nicht global aktiv.

```yaml
default_profile: openai_premium

purposes:
  structured_decision:
    profile: hf_pool_structured
    fallback: groq_fast
```

### Nutzen

```text
- erstes echtes HF-Modell kann geprüft werden
- Provider-Metadaten, Latenz und Failure-Verhalten werden messbar
- keine Gefahr für normalen Chatbetrieb
```

## 4. Minimalertrag Stufe 3 — structured_decision über hf_pool

### Ergebnis

Der erste echte Anwendungsfall für hf_pool ist nicht normaler Chat, sondern strukturierte Entscheidung.

```text
structured_decision:
  bevorzugt hf_pool / Qwen 4B
  fallback groq_fast oder bestehender Provider
```

Warum?

```text
- kurze Prompts
- gut testbar
- niedrige Kosten
- klarer Output
- Pydantic-AI-kompatibel
- weniger Risiko als normal_chat
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_pydantic_decisions.py tests/test_hf_pool_fallback_routing.py
```

Optional live:

```bash
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_structured_decision_hf.py
```

### Nutzen

```text
- erster echter Nutzen aus Deep Research
- Qwen/Qwen3-4B-Instruct-2507 kann für strukturierte Entscheidungen getestet werden
- Pydantic AI bekommt einen passenden Modellpfad
```

## 5. Minimalertrag Stufe 4 — Qdrant nur als Health + leere Collections

### Ergebnis

Qdrant wird noch nicht sofort für Usermemory oder Bibliothekar benötigt. Zuerst:

```text
- Qdrant Healthcheck
- ensure_collection()
- zwei Collections vorbereiten
- keine Pflicht beim Botstart
```

Collections:

```text
teebotus_user_memory
teebotus_bibliothekar_chunks
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_qdrant_health.py tests/test_qdrant_collections.py
python3 -m TeeBotus --runtime-status --channels telegram
```

### Nutzen

```text
- Qdrant ist kontrolliert integrierbar
- Runtime-Status kann Qdrant anzeigen
- spätere Memory-/Bibliothekar-Indizes haben stabile Basis
```

## 6. Minimalertrag Stufe 5 — QdrantMemoryIndex ohne automatische Nutzung

### Ergebnis

```text
- QdrantMemoryIndex existiert.
- FakeEmbeddingProvider existiert.
- index_memory/search/delete funktionieren in Tests.
- Kein Klartext in Qdrant.
- Noch kein automatisches Produktivrouting.
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_qdrant_memory_index.py
```

### Nutzen

```text
- Usermemory kann semantisch suchbar werden.
- Datenschutzregel ist getestet.
- AccountStore bleibt Wahrheit.
```

## 7. Minimalertrag Stufe 6 — MemorySearchService opt-in

### Ergebnis

```text
MemorySearchService:
  keyword/metadata search bleibt Standard
  qdrant search optional
  merge_memory_candidates()
```

Aktivierung nur explizit:

```yaml
memory_search:
  semantic_enabled: false
```

Später:

```yaml
memory_search:
  semantic_enabled: true
  semantic_backend: qdrant
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_memory_search_service.py
```

### Nutzen

```text
- keine Änderung am Memory-Verhalten ohne Flag
- semantische Suche kann pro Instanz aktiviert werden
```

## 8. Minimalertrag Stufe 7 — Bibliothekar-Qdrant als optionaler Backend-Test

### Ergebnis

```text
- LocalBibliothekarBackend bleibt Standard
- QdrantBibliothekarIndex kann Testchunks indexieren
- bge-m3 ist vorbereitet, aber FakeEmbedding in Standardtests
- Haystack bleibt optionales Pipelinebackend
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_bibliothekar_qdrant_index.py tests/test_bibliothekar_service.py
```

### Nutzen

```text
- Bibliothekar bleibt lauffähig ohne Qdrant
- Qdrant-Index kann separat aufgebaut werden
- keine bestehende Bibliothekar-Funktion wird zerstört
```

## 9. Minimalertrag Stufe 8 — Pydantic AI mit FakeModel

### Ergebnis

```text
- TeeBotus/decisions existiert
- Pydantic-Schemas existieren
- FakeModel/TestModel Tests laufen
- keine echten Provider nötig
- Slash-Commands bleiben klassische Parser
```

### Akzeptanz

```bash
python3 -m pytest -q tests/test_decision_schemas.py tests/test_pydantic_decision_fake_model.py
```

### Nutzen

```text
- IntentDecision, MemoryCandidate und BibliothekarQueryDecision werden testbar
- LLM-Entscheidungen bekommen robuste Typen
- kein Live-Provider-Zwang
```

## 10. Minimalertrag: Was ausdrücklich NICHT im ersten Schritt passieren darf

```text
- hf_pool wird nicht sofort globaler Default.
- normal_chat wird nicht sofort auf hf_pool umgestellt.
- Qdrant wird nicht Pflicht für Usermemory.
- Qdrant wird nicht Pflicht für Bibliothekar.
- Haystack wird nicht Pflicht.
- Pydantic AI wird nicht für Slash-Commands vorgeschaltet.
- LangGraph/CrewAI werden nicht in den normalen Chatpfad gezogen.
- fehlende Provider erzeugen keinen Botstart-Abbruch.
```

## 11. Minimalertrag als Codex-Auftrag

```text
Implementiere den Minimalertrag aus Plan v3.3.

Ziele:
1. TeeBotus/llm/hf_pool als Paket.
2. hf_pool ist optional, lazy und non-fatal.
3. MockExecutor und Doctor/Status funktionieren.
4. hf_pool ist nicht default_profile.
5. Fehlende HF-Konfiguration erzeugt unavailable status, keinen Crash.
6. Qdrant-Health und Collection-Basis sind optional.
7. QdrantMemoryIndex existiert mit FakeEmbeddingProvider und ohne Klartext-Payload.
8. MemorySearchService unterstützt Qdrant opt-in.
9. Pydantic-Decision-Schemas existieren und laufen mit FakeModel.
10. Bestehende Tests bleiben grün.
```

## 12. Minimalertrag Definition of Done

```text
- python3 -m TeeBotus funktioniert ohne HF-Konfiguration.
- python3 -m TeeBotus --runtime-status --channels telegram funktioniert ohne HF/Qdrant.
- hf_pool status ist sichtbar.
- Qdrant status ist sichtbar, falls konfiguriert.
- Keine echten HF-Calls in Standardtests.
- Keine echten Qdrant-Abhängigkeiten in Standardtests, außer explizit markierte Integrationstests.
- AccountStore bleibt Wahrheit.
- Usermemory-Klartext landet nicht in Qdrant.
- LocalBibliothekarBackend bleibt Fallback.
- Pydantic-Schemas sind testbar.
```

## 13. Minimalertrag Reihenfolge für Codex

```text
MVP-1:
  hf_pool package + config parser + target dataclasses + nonfatal errors

MVP-2:
  hf_pool scheduler + state + doctor + runtime-status hooks

MVP-3:
  Routerintegration ohne default switch

MVP-4:
  Qdrant health + collection wrapper

MVP-5:
  EmbeddingProvider Protocol + FakeEmbeddingProvider

MVP-6:
  QdrantMemoryIndex

MVP-7:
  MemorySearchService opt-in

MVP-8:
  Decision schemas + FakeModel

MVP-9:
  Benchmarks quick mode für hf_pool, qdrant health, memory index, decisions
```

## 14. Mini-Architektur nach Minimalertrag

```text
TeeBotusEngine
  ├─ bestehender Chatpfad
  ├─ bestehender AccountStore
  ├─ bestehender Bibliothekar LocalBackend
  ├─ LLMRouter
  │    ├─ bestehende Provider
  │    └─ hf_pool optional/unavailable-aware
  ├─ MemorySearchService
  │    ├─ keyword/metadata default
  │    └─ qdrant opt-in
  ├─ QdrantHealth optional
  └─ Decisions
       └─ Pydantic Schemas + FakeModel tests
```

## 15. Warum dieser Minimalertrag sinnvoll ist

```text
- niedriges Risiko
- sofort testbar
- keine API-Kosten
- keine harten neuen Runtime-Abhängigkeiten
- keine Datenmigration
- keine Änderung des normalen Bot-Chats
- legt die Schienen für hf_pool, Qdrant und Pydantic
- bewahrt Rollback-Fähigkeit
```

Das ist der kleinste Schritt, der wirklich Architekturwert erzeugt.


## 4. HF-Pool-Konfiguration

Neue Datei:

```text
config/hf_pool.yaml
```

Beispiel v1:

```yaml
pools:
  default:
    strategy: purpose_weighted
    max_retries: 2
    timeout_seconds: 60
    cooldown_seconds_on_429: 900
    cooldown_seconds_on_5xx: 120
    cooldown_seconds_on_timeout: 120

    targets:
      - name: qwen_4b_structured
        kind: hf_router_chat
        base_url: https://router.huggingface.co/v1
        api_key_env: HF_TOKEN_MAIN
        model: Qwen/Qwen3-4B-Instruct-2507
        routed_model: Qwen/Qwen3-4B-Instruct-2507
        weight: 5
        purposes:
          - structured_decision
          - normal_chat
        required:
          supports_structured_output: true
          supports_tools: true

      - name: qwen_9b_budget
        kind: hf_router_chat
        base_url: https://router.huggingface.co/v1
        api_key_env: HF_TOKEN_MAIN
        model: Qwen/Qwen3.5-9B
        weight: 4
        purposes:
          - normal_chat
          - bibliothekar_answer
          - summarizer

      - name: gemma_4_quality
        kind: hf_router_chat
        base_url: https://router.huggingface.co/v1
        api_key_env: HF_TOKEN_MAIN
        model: google/gemma-4-31B-it
        weight: 2
        purposes:
          - psychology_explainer
          - bibliothekar_answer
          - summarizer

      - name: eurollm_de
        kind: hf_router_chat
        base_url: https://router.huggingface.co/v1
        api_key_env: HF_TOKEN_MAIN
        model: utter-project/EuroLLM-22B-Instruct-2512
        weight: 1
        purposes:
          - psychology_explainer
          - german_sensitive_style

      - name: dedicated_psychology_endpoint
        kind: hf_dedicated_endpoint_chat
        base_url: https://example.endpoints.huggingface.cloud/v1
        api_key_env: HF_ENDPOINT_PSY_TOKEN
        model: custom
        weight: 1
        purposes:
          - psychology_sensitive
        enabled: false
```

---

## 5. LLM-Profile und Routing aktualisieren

Aktuell existieren Profile wie `local_ollama`, `hf_mistral`, `groq_fast`, `gemini_flash`, `openai_premium`.

Neue Profile:

```yaml
profiles:
  hf_pool_default:
    provider: hf_pool
    model: pool:default
    api_key_env: ""

  hf_pool_structured:
    provider: hf_pool
    model: pool:default#structured_decision
    api_key_env: ""

  hf_pool_quality:
    provider: hf_pool
    model: pool:default#psychology_explainer
    api_key_env: ""

  hf_pool_bibliothekar:
    provider: hf_pool
    model: pool:default#bibliothekar_answer
    api_key_env: ""
```

Routing für Notebook-ohne-GPU-Kontext:

```yaml
default_profile: hf_pool_default

purposes:
  normal_chat:
    profile: hf_pool_default
    fallback: gemini_flash

  structured_decision:
    profile: hf_pool_structured
    fallback: groq_fast

  psychology_explainer:
    profile: hf_pool_quality
    fallback: openai_premium

  psychology_sensitive:
    profile: hf_pool_quality
    fallback: null

  bibliothekar_answer:
    profile: hf_pool_bibliothekar
    fallback: openai_premium

  summarizer:
    profile: hf_pool_bibliothekar
    fallback: gemini_flash

  private:
    profile: hf_pool_default
    fallback: null
```

Anmerkung: `private` heißt hier nicht „lokal“, weil auf dem Notebook ohne GPU lokale LLMs nicht Hauptpfad sind. `private` heißt: keine stillen Remote-Fallbacks, nur explizit erlaubter Provider.

---

## 6. Integration in vorhandenen LLM-Code

### 6.1 `normalize_llm_provider`

Ergänzen:

```python
if normalized in {"hf_pool", "huggingface_pool", "hfpool"}:
    return "hf_pool"
```

### 6.2 `build_text_llm_client`

Ergänzen:

```python
if resolved_provider == "hf_pool":
    from TeeBotus.llm.hf_pool.provider import HFPoolProvider
    return HFPoolProvider.from_model_selector(
        model=model,
        instructions=instructions,
        timeout=...,
        temperature=...,
        max_tokens=...,
    )
```

### 6.3 Remote-Fallback-Logik

`hf_pool` gilt als remote. In `profiles.py`:

```python
REMOTE_PROVIDERS = frozenset({"openai", "huggingface", "groq", "gemini", "hf_pool"})
```

### 6.4 Capabilities

Neue Capabilities:

```python
HF_POOL_TEXT_CAPABILITIES = LLMCapabilities(
    text=True,
    streaming=False,              # später
    previous_response_id=False,
    tools="target-dependent",
    web_search=False,
    images=False,
    speech=False,
    transcription=False,
    json_schema="target-dependent",
)
```

Im Code besser nicht String in bool-Feldern; stattdessen `TargetCapabilities` zusätzlich pflegen.

---

## 7. Modell-Buckets aus Deep Research

### 7.1 Generative Modelle

| Bucket | Primär | Sekundär | Kommentar |
|---|---|---|---|
| `normal_chat` | `Qwen/Qwen3.5-9B` | `Qwen/Qwen3-4B-Instruct-2507` | 9B als Budget-Allrounder, 4B als Billig-/Strukturmodell |
| `structured_decision` | `Qwen/Qwen3-4B-Instruct-2507` | `Qwen/Qwen2.5-7B-Instruct` | Tools/Structured/Preis wichtig |
| `psychology_explainer` | `google/gemma-4-31B-it` | `utter-project/EuroLLM-22B-Instruct-2512` | Gemma Qualität, EuroLLM Deutsch/EU-Sprachen |
| `bibliothekar_answer` | `google/gemma-4-31B-it` | `Qwen/Qwen3.5-9B` / `Mistral Small 3.1` | Quellengehorsam + Kontext |
| `summarizer` | `google/gemma-4-31B-it` | `Qwen/Qwen3.5-9B` | Langkontext + Faithfulness |
| `fallback_cheap` | `meta-llama/Llama-3.1-8B-Instruct` | Qwen 4B | nur Kosten-/Kompatibilitätsfallback |

### 7.2 Embeddings

| Bucket | Primär | Sekundär | Kommentar |
|---|---|---|---|
| `embedding_user_memory` | `intfloat/multilingual-e5-small` | `intfloat/multilingual-e5-base` | kurze Memories, Kosten und Durchsatz wichtig |
| `embedding_books` | `BAAI/bge-m3` | `jinaai/jina-embeddings-v3`, `Alibaba-NLP/gte-multilingual-base` | lange Chunks, mehrsprachig, Bibliothekar |
| `embedding_source_quality` | `intfloat/multilingual-e5-base` | `bge-m3` | Claim-/Source-Matching |

### 7.3 Reranker

| Bucket | Primär | Sekundär |
|---|---|---|
| `reranker` | `BAAI/bge-reranker-v2-m3` | `jinaai/jina-reranker-v2-base-multilingual` |
| `reranker_budget` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | none |

### 7.4 Source Quality

Nicht als einzelnes Chatmodell bauen, sondern Pipeline:

```text
SourceQualityPipeline
  1. Metadaten-/URL-/DOI-Check
  2. Claim Extraction
  3. Retrieval
  4. NLI/Stance:
       MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
  5. wissenschaftlicher Pfad:
       VeriSci/SciFact-artige Modelle
  6. Score:
       credible / maybe / weak / reject
```

---

## 8. Separate Embedding-Schicht

`hf_pool` ist für Textgenerierung. Embeddings und Reranker werden separat.

Neue Struktur:

```text
TeeBotus/embedding/
  __init__.py
  base.py
  config.py
  hf_provider.py
  qdrant_memory.py
  qdrant_bibliothekar.py
  reranker.py
  metrics.py
```

### 8.1 Interfaces

```python
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str], *, purpose: str = "") -> list[list[float]]:
        ...

class RerankerProvider(Protocol):
    def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        ...
```

### 8.2 HFEmbeddingProvider

Ziele:

```text
- Feature Extraction über HF Inference Providers
- optional HF TEI Endpoint
- Batches
- Retry/Cooldown
- Metrics
```

### 8.3 QdrantMemoryIndex

```text
AccountStore bleibt Wahrheit.
QdrantMemoryIndex ist semantischer Suchindex.
Kein Klartext im Qdrant-Payload.
```

Payload:

```json
{
  "schema": "teebotus_qdrant_memory_v1",
  "schema_version": 3,
  "instance_name": "Depressionsbot",
  "account_scope": "abgeleiteter scope hash, keine rohe account_id",
  "memory_id": "mem_...",
  "embedding_model": "intfloat/multilingual-e5-small",
  "embedding_dimensions": 384
}
```

Ablauf:

```text
Memory speichern:
  AccountStore verschlüsselt Payload
  Account-Memory-EmbeddingProvider erzeugt Vektor nur lokal:
    hash/local oder explizit lokaler HTTP-Endpoint
    kein HF-Remote-Default ohne Endpoint
  QdrantMemoryIndex speichert Vektor + harmlose Metadaten

Memory suchen:
  Query embedding
  Qdrant filtert schema + schema_version + account_scope + instance + Embedding-Vertrag
  Client verwirft stale/leaky Treffer defensiv mit falschem schema, schema_version,
  embedding_model oder embedding_dimensions
  Ergebnis liefert memory_id
  AccountStore prüft Rechte und entschlüsselt
  Kontext wird gebaut
```

---

## 9. Bibliothekar v3: Local + LlamaIndex + Haystack

### 9.1 Aktueller Zustand

`BibliothekarService` existiert bereits mit Backend-Protokoll, LocalBackend und HaystackBackend. Nicht neu bauen.

### 9.2 Neue Richtung

Für einige Hundert Bücher und „mit den Docs chatten“:

```text
1. LocalBackend bleibt immer Fallback.
2. LlamaIndexBackend als Experiment für Doc-Chat und Q&A.
3. HaystackBackend bleibt für kontrollierte Pipeline/Qdrant-Betrieb.
```

### 9.3 Warum LlamaIndex zuerst testen?

```text
- besser für „chatte mit meinen Dokumenten“
- schnellerer Prototyp
- QueryEngine/ChatEngine passt zum Psychologiekontext
- für einige Hundert Bücher wahrscheinlich angenehmer als Haystack
```

### 9.4 Warum Haystack behalten?

```text
- kontrollierte Ingestion-Pipelines
- SourceHarvester
- große Bibliothek
- Hybrid Retrieval / Reranker / Metadata Routing
- produktionsnahe Komponenten
```

### 9.5 Zielstruktur

```text
TeeBotus/runtime/bibliothekar_service.py
  BibliothekarBackend Protocol
  LocalBibliothekarBackend
  HaystackBibliothekarBackend

TeeBotus/bibliothekar/
  cli.py
  llamaindex_backend.py
  haystack_backend_helpers.py
  source_harvester.py
  citations.py
```

`TeeBotus.runtime.bibliothekar_service` bleibt Kompatibilitätsschicht. Neue große Backend-Dateien können in `TeeBotus/bibliothekar/` wohnen.

---

## 10. SourceHarvester

Wenn Bots Quellen finden und herunterladen sollen:

```text
Nicht direkt in Hauptbibliothek schreiben.
Immer erst in Quarantäne.
```

Struktur:

```text
library/
  inbox/
  quarantine/
  accepted/
  rejected/
```

Pipeline:

```text
URL entdeckt
  ↓
Download mit Größenlimit
  ↓
Hash / Dedupe
  ↓
MIME / Dateityp prüfen
  ↓
Metadaten extrahieren
  ↓
SourceQualityPipeline
  ↓
Review/Auto-Regel
  ↓
Bibliothekar ingestion
```

Safety:

```text
- keine ausführbaren Dateien
- Größenlimit
- MIME/Extension prüfen
- robots / Nutzungsrechte beachten
- keine blind heruntergeladenen Quellen in Psych-Antworten
- Quellenstatus in Citation-Payload markieren:
    trusted / unreviewed / weak / rejected
```

---

## 11. Agenten v3

### 11.1 CrewAI

CrewAI ist sinnvoll für Spezialaufgaben:

```text
Bibliothekar Expedition:
  Researcher
  Retriever
  Psychology Explainer
  Skeptic
  Safety Reviewer
  Formatter

Source Quality Expedition:
  Harvester
  Metadata Inspector
  Claim Extractor
  NLI Verifier
  Summary Writer

Anki Expedition:
  Source Reader
  Card Writer
  Cloze Checker
  Scientific Hygiene Reviewer
```

Nicht für normale Botantworten.

### 11.2 LangGraph

LangGraph für kontrollierte, langlebige Workflows:

```text
Proactive-Agent:
  observe → plan → due-selection → safety → dispatch → record

Bibliothekar Deep Query:
  classify → retrieve → rerank → answer → citation_check → fallback

Codex Task:
  authorize → plan → sandbox → execute → summarize → approval

SourceHarvester:
  discover → download → quarantine → score → ingest/reject
```

### 11.3 AutoGen

Zurückstellen. Nur für Agentenlabor / Code-Sandbox-Experimente, nicht Hauptplan.

---

## 12. Benchmark- und Eval-Plan

Plan2s Benchmark-Zusatz wird in v3 früher gezogen.

### 12.1 Neue Benchmark-Struktur

```text
scripts/run_benchmarks.py

TeeBotus/benchmarks/
  __init__.py
  core.py
  suite.py
  reporting.py
  llm_routing.py
  hf_pool.py
  langgraph_flows.py
  pydantic_ai.py
  mcp.py
  qdrant.py
  memory.py
  bibliothekar.py
  proactive.py
  youtube.py
  runtime_health.py
  source_quality.py
  adapters.py
```

### 12.2 Standard: keine Live-Kosten

```bash
python3 scripts/run_benchmarks.py --quick
```

Der Quick-Lauf schreibt Markdown + JSON standardmaessig nach Obsidian-Incoming und sendet den Markdown-Bericht messenger-agnostisch an Admin-Accounts. Reine lokale Pruefungen koennen `--no-admin-notify` und `--no-obsidian` setzen.

### 12.3 Live nur explizit

```bash
python3 scripts/run_benchmarks.py --live-hf --live-qdrant --profile hf_pool_default
```

### 12.4 HF-Pool-Evals

```text
- structured_decision JSON validity
- normal_chat latency
- psychology_explainer quality rubric
- bibliothekar_answer citation faithfulness
- summarizer faithfulness
- provider failure fallback
- cooldown behavior
```

### 12.5 Retrieval-Evals

```text
- e5-small vs e5-base für Usermemory
- bge-m3 vs e5-base für Bücher
- bge-reranker-v2-m3 vs ohne reranker
- LocalBackend vs LlamaIndexBackend vs HaystackBackend
```

---

## 13. Phasenplan v3

### Phase 0 — Baseline und Ist-Zustand sichern

```bash
git status
python3 -m TeeBotus --version
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m pytest -q
```

Akzeptanz:

```text
- Main startet.
- Tests grün oder bekannte Fehler dokumentiert.
- pyproject mit Extras bleibt erhalten.
```

### Phase 1 — `hf_pool` Paket-Skeleton

```text
- TeeBotus/llm/hf_pool/ anlegen
- config.py, targets.py, scheduler.py, state.py
- config/hf_pool.yaml Fixture
- keine echten HF Calls
```

Tests:

```bash
python3 -m pytest -q tests/test_hf_pool_config.py tests/test_hf_pool_scheduler.py
```

### Phase 2 — HFPoolProvider Mock + Router-Integration

```text
- HFPoolProvider.create_reply()
- MockExecutor
- normalize_llm_provider("hf_pool")
- build_text_llm_client unterstützt hf_pool
- Profile hf_pool_default ergänzen
```

Tests:

```bash
python3 -m pytest -q tests/test_hf_pool_provider.py tests/test_llm_router.py
```

### Phase 3 — HF OpenAI-compatible Executor

```text
- POST /chat/completions
- Antwort zu LLMResponse normalisieren
- Usage extrahieren
- Secrets redaction
- Timeout/Cooldown
```

Live nur optional:

```bash
TEEBOTUS_LIVE_HF=1 python3 -m pytest -q tests/live/test_hf_pool_live.py
```

### Phase 4 — DR-Modellprofile einsetzen

```text
- Qwen3-4B für structured_decision
- Qwen3.5-9B für normal_chat/budget
- Gemma 4 31B für psychology/bibliothekar/summarizer
- EuroLLM für Deutsch-Spezialprofil
```

Akzeptanz:

```text
- Routing pro purpose wählt erwarteten Target.
- Remote-Fallback bleibt explizit kontrolliert.
```

### Phase 5 — Embedding-Paket

```text
- TeeBotus/embedding/
- HFEmbeddingProvider
- Embedding config
- FakeProvider Tests
```

Tests:

```bash
python3 -m pytest -q tests/test_embedding_provider.py
```

### Phase 6 — QdrantMemoryIndex

```text
- Qdrant optional dependency aus rag extra
- MemoryEmbeddingIndex Interface
- QdrantMemoryIndex
- account_scope Filter; keine rohe account_id im normalen Payload oder Suchfilter
- delete_memory/delete_account
- kein Klartext in Payload
```

Tests:

```bash
python3 -m pytest -q tests/test_qdrant_memory_index.py
```

### Phase 7 — MemorySearchService

```text
- Keyword/Metadata Search + Qdrant Search mergen
- Reranking optional
- AccountStore bleibt Wahrheit
```

Akzeptanz:

```text
- /reset_memorys entfernt auch Qdrant-Vektoren.
- Export erklärt semantischen Index.
- Rebuild aus AccountStore möglich.
```

### Phase 8 — Bibliothekar Doc-Chat

```text
- LocalBackend bleibt Fallback
- LlamaIndexBackend experimentell
- HaystackBackend bleibt optional
- bge-m3 embeddings für Bücher evaluieren
- bge-reranker-v2-m3 optional
```

Tests:

```bash
python3 -m pytest -q tests/test_bibliothekar_service.py tests/test_llamaindex_backend.py
```

### Phase 9 — SourceHarvester

```text
- URL discovery nicht blind in Hauptindex
- quarantine
- metadata
- source quality pipeline
- NLI verifier
```

### Phase 10 — Pydantic AI Decisions

```text
- IntentDecision
- MemoryCandidate
- ReminderDecision
- ToolSafetyDecision
- BibliothekarQueryClassification
```

### Phase 11 — LangGraph / CrewAI Spezialagenten

```text
- LangGraph Pilot: Bibliothekar Deep Query
- CrewAI Pilot: Quellen-/Anki-Expedition
- AutoGen nicht priorisieren
```

### Phase 12 — Telegram Runtime Slot

Plan2s Telegram-Slot-Migration bleibt gültig, aber nicht vor hf_pool/embedding:

```text
- TelegramRuntimeSlot
- Long-Polling als Transport
- später Webhook optional
```

---

## 14. Konkrete Codex-Aufträge v3

### Auftrag A — HF-Pool Paket

```text
Erstelle TeeBotus/llm/hf_pool als Paket.
Implementiere Config, Target, Scheduler, State und MockProvider.
Noch keine echten Netzaufrufe.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_hf_pool_config.py tests/test_hf_pool_scheduler.py
```

### Auftrag B — HF-Pool Provider-Integration

```text
Integriere provider=hf_pool in normalize_llm_provider und build_text_llm_client.
Ergänze config/llm_profiles.yaml und config/llm_routing.yaml um hf_pool Profile.
Nutze MockExecutor in Tests.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_llm_router.py tests/test_hf_pool_provider.py
```

### Auftrag C — HF Executor

```text
Baue OpenAI-kompatible HF-Chat-Completion-Ausführung.
Implementiere Fehlerklassen, Token-Redaction, Cooldown und Usage Events.
Live-Tests nur hinter explizitem Flag.
```

### Auftrag D — HF Modellmatrix

```text
Übernehme DR-Modellkandidaten in config/hf_pool.yaml.
Buckets:
normal_chat, structured_decision, psychology_explainer,
bibliothekar_answer, summarizer.
```

### Auftrag E — Embeddings/QdrantMemoryIndex

```text
Baue TeeBotus/embedding.
Implementiere HFEmbeddingProvider und QdrantMemoryIndex.
AccountStore bleibt Wahrheit.
Kein Klartext in Qdrant.
```

### Auftrag F — Retrieval Benchmarks

```text
Benchmarke:
- e5-small vs e5-base für Usermemory
- bge-m3 vs e5-base für Bücher
- mit/ohne reranker
- Local vs LlamaIndex vs Haystack
```

### Auftrag G — Bibliothekar LlamaIndexBackend

```text
Ergänze optionales LlamaIndexBackend hinter BibliothekarService.
Nicht LocalBackend oder HaystackBackend löschen.
Doc-Chat-Fokus.
```

### Auftrag H — Source Quality

```text
Baue SourceQualityPipeline mit NLI-Baustein.
Kein einzelnes LLM als Wahrheitsrichter.
Quarantäne vor Hauptindex.
```

### Auftrag I — Benchmarks für alles

```text
Setze Plan2 Benchmarkauftrag um.
Standardbenchmarks ohne API-Kosten.
Livebenchmarks optional.
```

---

## 15. Definition of Done v3

```text
- hf_pool ist ein Paket.
- HFPoolProvider ist in TeeBotus LLM-Router integrierbar.
- DR-Modelle sind als konfigurierte Targets/Buckets hinterlegt.
- Live-HF-Tests sind optional und standardmäßig aus.
- LiteLLM bleibt generischer Provideradapter.
- OpenAIClient bleibt Spezialclient.
- Embeddings sind separat von Chat.
- QdrantMemoryIndex existiert als Suchindex, nicht als Wahrheitsspeicher.
- AccountStore bleibt verschlüsselter Wahrheitsspeicher.
- BibliothekarService behält LocalBackend und HaystackBackend.
- LlamaIndexBackend ist optionaler Doc-Chat-Pilot.
- Benchmarks liefern Markdown + JSON nach /home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming und der Quick-CLI-Lauf sendet den Markdown-Bericht an Admin-Accounts.
- Keine Secrets im Repo oder Benchmarkoutput.
```

---

## 16. Endformel

```text
TeeBotus ist der Hof.
LiteLLM ist der allgemeine Torwächter.
hf_pool ist die Hugging-Face-Gilde.
OpenAIClient ist der Spezialmagier.
AccountStore ist der Tresor.
Qdrant ist der Suchhund.
BibliothekarService ist die Bibliothekstür.
LlamaIndex ist der Gesprächs-Bibliothekar.
Haystack ist die Industriebibliothek.
Pydantic AI ist der Formularbeamte.
LangGraph ist der Ablaufmeister.
CrewAI ist das Expeditionsteam.
```

---

# Ergänzung v3.1 — Qdrant als gemeinsamer Index, Haystack als Pipeline-Backend, Pydantic AI als Decision-Schicht

**Status:** Diese Ergänzung überschreibt die betreffenden Stellen aus v3, ohne die Grundarchitektur zu kippen.

## A. Neue verbindliche Architekturentscheidung

```text
Einheitliche Zukunft:
  Qdrant für Bibliothekar und Usermemory-Index
  AccountStore bleibt SQLite/Postgres für Wahrheit
```

Das bedeutet:

```text
AccountStore:
  Wahrheitsspeicher
  Verschlüsselung
  Accountrechte
  Export
  Löschung
  Migration
  Audit

Qdrant:
  semantischer Suchindex
  Vektoren
  harmlose Metadaten
  keine Usermemory-Klartexte

BibliothekarService:
  Quellen-/Buch-Retrieval
  Qdrant als gemeinsamer Suchindex für Buchchunks

MemorySearchService:
  Usermemory-Retrieval
  Qdrant als semantischer Index
  AccountStore entschlüsselt nur Treffer
```

Nicht mehr:

```text
Haystack als Usermemory-Speicher
Qdrant als Wahrheitsspeicher
Haystack als Muss-Komponente
```

Sondern:

```text
Qdrant = gemeinsamer semantischer Index
AccountStore = Wahrheit
Haystack = optionales Pipeline-/Orchestrierungs-Backend für Bibliothekar und SourceHarvester
Pydantic AI = typisierte Decision-Schicht
```

---

## B. Was ist jetzt mit Haystack?

Haystack bleibt drin, aber mit klar begrenzter Rolle.

### B.1 Haystack bleibt optional

Haystack wird **nicht** der Hauptspeicher für Usermemory und auch nicht zwingend der einzige Bibliothekar. Haystack bleibt ein optionales Backend, wenn wir komplexere RAG-/Ingestion-Pipelines brauchen.

```text
BibliothekarService
  ├─ LocalBibliothekarBackend
  ├─ LlamaIndexBackend optional, Doc-Chat/Q&A
  └─ HaystackBibliothekarBackend optional, Pipeline/Qdrant/Reranker
```

### B.2 Haystack ist gut für

```text
- Indexing-Pipelines
- Query-Pipelines
- DocumentStore-Abstraktion
- Retriever/Reranker-Ketten
- SourceHarvester-Ingestion
- Hybrid Retrieval
- Metadata Filtering
- spätere große Bibliothek
- kontrollierte Quellenverarbeitung
```

### B.3 Haystack ist nicht gut als

```text
- Wahrheitsspeicher für Usermemory
- AccountStore-Ersatz
- Verschlüsselungs-/Rechte-/Export-System
- Pflichtabhängigkeit im Bot-Kern
```

### B.4 Praktische Rolle

```text
Jetzt:
  LocalBackend + Qdrant-Index priorisieren.

Danach:
  LlamaIndexBackend testen, wenn "mit Dokumenten chatten" im Vordergrund steht.

Später:
  HaystackBackend für SourceHarvester, große Bibliothek, Hybrid Retrieval, Reranking.
```

### B.5 Haystack und Qdrant

Haystack darf Qdrant nutzen, aber Qdrant ist nicht "Haystacks Eigentum".

```text
QdrantCollections:
  teebotus_user_memory
  teebotus_bibliothekar_chunks

HaystackBibliothekarBackend:
  nutzt nur teebotus_bibliothekar_chunks
  niemals teebotus_user_memory als Klartext-DocumentStore
```

Für Usermemory gilt:

```text
Haystack darf später eine Retrieval-Pipeline über Qdrant bauen,
aber der AccountStore bleibt der einzige Ort, an dem Usermemory-Klartext entschlüsselt wird.
```

---

## C. Pydantic AI: Ja, aber als Decision-Schicht

Pydantic AI wird eingebaut, aber nicht als Bot-Kern und nicht als generischer Chat-Agent.

### C.1 Rolle

```text
Pydantic AI:
  strukturierte LLM-Entscheidungen
  validierte Outputs
  Testbarkeit
  JSON-/Schema-Sicherheit
```

Nicht:

```text
Pydantic AI:
  ersetzt TeeBotusEngine
  ersetzt LangGraph
  ersetzt LiteLLM
  ersetzt AccountStore
```

### C.2 Warum passt es gut?

TeeBotus hat viele Stellen, an denen natürliche Sprache in klare Entscheidungen überführt werden muss:

```text
- IntentDecision
- MemoryCandidate
- ReminderDecision
- BibliothekarQueryClassification
- ToolSafetyDecision
- SourceQualityDecision
- AgentTaskDecision
- YouTubeOptionsDecision
```

Diese Ergebnisse sollen nicht als freier Text geparst werden, sondern als typisierte Modelle.

### C.3 Paketstruktur

```text
TeeBotus/decisions/
  __init__.py
  schemas.py
  pydantic_agent.py
  intent.py
  memory.py
  reminder.py
  bibliothekar.py
  source_quality.py
  tool_safety.py
  fake_model.py
```

### C.4 Schemas

```python
from pydantic import BaseModel, Field
from typing import Literal


class IntentDecision(BaseModel):
    intent: Literal[
        "chat",
        "account",
        "register",
        "login",
        "memory_reset",
        "reminder",
        "youtube_transcript",
        "bibliothekar_query",
        "tool_request",
        "source_harvest",
        "unknown",
    ]
    confidence: float = Field(ge=0, le=1)
    reason_short: str


class MemoryCandidate(BaseModel):
    should_store: bool
    memory_type: Literal[
        "preference",
        "habit",
        "project",
        "relationship",
        "health_context",
        "communication_style",
        "none",
    ]
    text: str
    sensitivity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)


class BibliothekarQueryDecision(BaseModel):
    should_query_bibliothekar: bool
    query: str
    filters: dict[str, str] = {}
    requires_sources: bool = True
    confidence: float = Field(ge=0, le=1)


class ToolSafetyDecision(BaseModel):
    allowed: bool
    requires_confirmation: bool
    reason: str
    risk_level: Literal["low", "medium", "high", "blocked"]


class SourceQualityDecision(BaseModel):
    status: Literal["trusted", "usable", "weak", "reject", "needs_review"]
    reason: str
    requires_human_review: bool
    confidence: float = Field(ge=0, le=1)
```

### C.5 Modellrouting für Pydantic AI

Pydantic AI soll den TeeBotus LLM-Router nutzen, nicht direkt irgendeinen Provider.

```text
structured_decision:
  preferred: hf_pool / Qwen3-4B-Instruct
  fallback: groq_fast oder gemini_flash
```

Deep Research legt nahe, `Qwen/Qwen3-4B-Instruct-2507` für strukturierte Entscheidungen zu testen, weil es im Research als günstiger Kandidat mit Tools/Structured-Support und großem Kontext auftaucht.

### C.6 Regeln

```text
Slash-Commands:
  immer klassische Parser zuerst

Pydantic AI:
  nur bei natürlicher Sprache oder unklaren Optionen

confidence < 0.70:
  nicht automatisch handeln

sensitivity == high:
  nicht automatisch speichern

ToolSafetyDecision:
  darf riskante Tools blockieren,
  aber Freigabe eines riskanten Tools erfordert trotzdem Policy/Allowlist

MemoryCandidate:
  Vorschlag, nicht Wahrheit
  AccountStore entscheidet final
```

### C.7 Tests

```text
tests/test_decision_schemas.py
tests/test_pydantic_decision_fake_model.py
tests/test_memory_candidate_decision.py
tests/test_bibliothekar_query_decision.py
tests/test_tool_safety_decision.py
```

Standardtests nutzen Fake/TestModel, keine echten Provider.

---

## D. Qdrant: zwei Collections, klare Grenzen

### D.1 Collections

```text
teebotus_user_memory
teebotus_bibliothekar_chunks
```

Warum getrennt?

```text
- unterschiedliche Embedding-Modelle
- verschiedene Chunkgrößen
- verschiedene Datenschutzanforderungen
- verschiedene Löschlogik
- verschiedene Payload-Schemas
- Usermemory ist sensibler als Bibliothekschunks
```

### D.2 Usermemory Collection

```json
{
  "schema": "teebotus_qdrant_memory_v1",
  "schema_version": 3,
  "instance_name": "Depressionsbot",
  "account_scope": "abgeleiteter scope hash, keine rohe account_id",
  "memory_id": "mem_...",
  "embedding_model": "intfloat/multilingual-e5-small",
  "embedding_dimensions": 384
}
```

**Kein Klartext. Keine Chat-Zitate. Keine Messenger-ID. Keine rohe `account_id`. Keine klinischen Kategorien, Zeitstempel, Scores oder Hashes aus dem Inhalt.**

### D.3 Bibliothekar Collection

```json
{
  "instance_name": "Depressionsbot",
  "chunk_id": "chunk_...",
  "source_id": "sha256:...",
  "title": "...",
  "author": "...",
  "relative_path": "...",
  "file_sha256": "...",
  "file_type": "pdf",
  "language": "de",
  "page_start": 12,
  "page_end": 13,
  "chapter": "...",
  "section": "...",
  "license": "private",
  "ingested_at": "2026-06-16T...",
  "embedding_model": "BAAI/bge-m3",
  "schema_version": 1
}
```

### D.4 Embedding-Modelle

Aus Deep Research übernehmen:

```text
Usermemory:
  intfloat/multilingual-e5-small
  intfloat/multilingual-e5-base

Bibliothekar:
  BAAI/bge-m3
  jinaai/jina-embeddings-v3 als Alternative
  Alibaba-NLP/gte-multilingual-base als Alternative

Reranker:
  BAAI/bge-reranker-v2-m3
  jinaai/jina-reranker-v2-base-multilingual
```

### D.5 Neue Pakete

```text
TeeBotus/embedding/
  __init__.py
  base.py
  config.py
  hf_provider.py
  qdrant_client.py
  qdrant_memory.py
  qdrant_bibliothekar.py
  reranker.py
  rebuild.py
  health.py
```

### D.6 MemorySearchService

```text
TeeBotus/runtime/memory_search.py
  MemorySearchService
  KeywordMemorySearch
  QdrantMemorySearch
  merge_memory_candidates()
```

Ablauf:

```text
User fragt
  ↓
MemorySearchService
  ↓
Query-Embedding
  ↓
Qdrant account_scope-filtered search
  ↓
memory_id-Liste
  ↓
AccountStore prüft Rechte und entschlüsselt
  ↓
Prompt-Kontext
```

---

## E. Aktualisierte Phasen

### Phase 0 — Baseline

```bash
python3 -m TeeBotus --version
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m pytest -q
```

### Phase 1 — hf_pool Paket

```text
TeeBotus/llm/hf_pool/
  config.py
  targets.py
  scheduler.py
  state.py
  provider.py
  executor.py
  redaction.py
```

Keine echten Calls in Standardtests.

### Phase 2 — hf_pool Integration

```text
normalize_llm_provider("hf_pool")
build_text_llm_client unterstützt hf_pool
config/llm_profiles.yaml ergänzt hf_pool_* Profile
config/llm_routing.yaml routet purposes auf hf_pool
```

### Phase 3 — HF Executor und DR-Modellmatrix

```text
OpenAI-compatible HF Router Executor
Usage/Metrics
Cooldown
Targets aus Deep Research:
  Qwen 4B
  Qwen 9B
  Gemma 4 31B
  EuroLLM
```

### Phase 4 — Embedding-Paket

```text
EmbeddingProvider Protocol
HFEmbeddingProvider
FakeEmbeddingProvider
RerankerProvider
```

### Phase 5 — Qdrant Basis

```text
QdrantClient wrapper
Collection ensure/create
Healthcheck
Runtime Status
```

### Phase 6 — QdrantMemoryIndex

```text
Usermemory semantisch suchbar
AccountStore bleibt Wahrheit
kein Klartext in Qdrant
/delete und /reset_memorys löschen Indexeinträge mit
```

### Phase 7 — Bibliothekar Qdrant Index

```text
teebotus_bibliothekar_chunks
bge-m3 embeddings
Citation-Metadaten erhalten
LocalBackend bleibt Fallback
```

### Phase 8 — Pydantic AI Decision-Schicht

```text
TeeBotus/decisions/
Schemas
FakeModel Tests
structured_decision routing über hf_pool
```

### Phase 9 — LlamaIndexBackend Pilot

```text
Doc-Chat mit einigen Hundert Büchern
BibliothekarService Backend
Qdrant als Vector Store, wenn sinnvoll
```

### Phase 10 — HaystackBackend schärfen

```text
Haystack nur für:
  große Bibliothek
  SourceHarvester
  komplexe Ingestion
  Hybrid Retrieval
  Reranker-Pipelines
```

### Phase 11 — SourceHarvester

```text
Quarantäne
Metadaten
Dedupe
SourceQualityDecision
NLI/Verifier-Pipeline
kein Blind-Ingest
```

### Phase 12 — LangGraph / CrewAI

```text
LangGraph:
  Bibliothekar Deep Query
  SourceHarvester Workflow
  Proactive-Agent

CrewAI:
  Quellen-Expedition
  Anki-Expedition
  Psychologie-Erklärteam

AutoGen:
  zurückstellen
```

---

## F. Aktualisierte Codex-Aufträge

### Auftrag 1 — hf_pool Paket

```text
Erstelle TeeBotus/llm/hf_pool als Paket.
Implementiere Config, Targets, Scheduler, State, Provider und MockExecutor.
Keine echten HF Calls.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_hf_pool_config.py tests/test_hf_pool_scheduler.py tests/test_hf_pool_provider.py
```

### Auftrag 2 — hf_pool Routerintegration

```text
provider=hf_pool in normalize_llm_provider und build_text_llm_client integrieren.
Profile und Routing ergänzen.
Remote-Fallback-Regeln respektieren.
```

### Auftrag 3 — Embedding-Paket

```text
TeeBotus/embedding anlegen.
EmbeddingProvider und FakeEmbeddingProvider.
HFEmbeddingProvider vorbereiten.
```

### Auftrag 4 — QdrantMemoryIndex

```text
QdrantMemoryIndex implementieren.
Kein Klartext in Payload.
schema, schema_version, abgeleiteter account_scope und instance_name Filter;
rohe account_id nur fuer explizite lokale Legacy-Cleanup-Migration, dort breit
genug fuer schema-lose Altlasten.
delete_memory, delete_account, rebuild.
```

### Auftrag 5 — MemorySearchService

```text
Keyword/Metadata Search und Qdrant Search mergen.
AccountStore entschlüsselt nur Treffer.
```

### Auftrag 6 — Bibliothekar Qdrant

```text
BibliothekarService nutzt Qdrant für teebotus_bibliothekar_chunks.
LocalBackend bleibt Fallback.
bge-m3 als Standard für Buchchunks.
```

### Auftrag 7 — Pydantic AI Decisions

```text
TeeBotus/decisions Paket.
Schemas für Intent, MemoryCandidate, Reminder, ToolSafety, BibliothekarQuery.
FakeModel Tests.
structured_decision Bucket über hf_pool/Qwen.
```

### Auftrag 8 — LlamaIndexBackend Pilot

```text
Optionales Backend hinter BibliothekarService.
Fokus: mit Docs chatten.
Kein Ersatz für LocalBackend/HaystackBackend.
```

### Auftrag 9 — HaystackBackend Pipeline

```text
HaystackBackend für SourceHarvester und große Bibliothek schärfen.
QdrantDocumentStore nur für Bibliothekar-Collection.
Nicht für Usermemory-Klartext.
```

---

## G. Definition of Done v3.1

```text
- hf_pool ist Paket und in Router integrierbar.
- Qdrant läuft als gemeinsamer semantischer Index.
- AccountStore bleibt Wahrheit.
- Usermemory-Klartext landet nicht in Qdrant/Haystack.
- Bibliothekar nutzt Qdrant für Buchchunks.
- Pydantic AI ist als Decision-Schicht eingebaut.
- Haystack bleibt optionales Pipeline-Backend.
- LlamaIndexBackend ist optionaler Doc-Chat-Pilot.
- Benchmarks messen hf_pool, QdrantMemoryIndex, Bibliothekar-Qdrant, Pydantic Decisions.
- Runtime-Status zeigt Qdrant, Collections, hf_pool Health und Decision Provider.
```

---

## H. Aktualisierte Endformel

```text
AccountStore ist der Tresor.
Qdrant ist der gemeinsame Suchhund.
BibliothekarService ist die Bibliothekstür.
LocalBackend ist das Notizregister.
LlamaIndex ist der Gesprächsbibliothekar.
Haystack ist die Industriebibliothek und Ingestionsmaschine.
Pydantic AI ist der typisierte Entscheidungsbeamte.
hf_pool ist die Hugging-Face-Gilde.
LiteLLM bleibt der allgemeine Torwächter.
OpenAIClient bleibt der Spezialmagier.
LangGraph ist der Ablaufmeister.
CrewAI ist das Expeditionsteam.
```
