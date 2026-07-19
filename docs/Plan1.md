# TeeBotus Installations- und Migrationsplan

**Ziel:** TeeBotus schrittweise zu einer providerneutralen, lokalen und RAG-faehigen Bot-Plattform ausbauen, ohne den bestehenden Startpfad, Telegram-Betrieb, Account-Memory oder Signal/Matrix-Runtime zu zerbrechen.

**Stand:** 2026-06-15  
**Repo-Kontext:** `H234598/TeeBotus`, Branch `main`  
**Leitlinie:** Keine Big-Bang-Migration. Bestehendes laeuft weiter, neue Faehigkeiten werden additiv angebaut.

## Implementierungsstand

Stand: 2026-06-19

Quelle:

- `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/Plan1.md` ist in `docs/Plan1.md` integriert.
- Download-SHA256: `c96dec8df17fc404731d9952e16b4994a9e13de1b1db7712067786fd7d3836b6`
- Der Dokumentkoerper folgt dem aktuellen Download-Stand; dieser Kopf fuehrt den Repo-Status analog zu `docs/Codex_Outbox_History_Plan.md`.

Umgesetzt:

- Der Plan liegt versioniert unter `docs/` und bleibt als historische Baseline erhalten.
- Die harten Start-, Runtime-, Account-Memory- und OpenAIClient-Invarianten bleiben die Kompatibilitaetsgrundlage.
- LLM-, Bibliothekar- und Agenten-Themen aus Plan1 werden in Plan2 und Plan3 detaillierter fortgeschrieben.

Offen:

- Plan1 wird nicht als eigene parallele Umsetzungsqueue gefuehrt.
- Bei Detailkonflikten gewinnen Plan2/Plan3 oder spezifischere Plaene, solange die harten Invarianten aus Plan1 nicht verletzt werden.

---

## 1. Zielarchitektur

TeeBotus soll nicht auf ein einzelnes Agentenframework umgezogen werden. Die bestehende Engine bleibt der Kern. Neue Frameworks werden als klar getrennte Dienste/Module eingebunden.

```text
Messenger-Adapter
  ├─ Telegram
  ├─ Signal
  └─ Matrix

        ↓ IncomingEvent

TeeBotusEngine / bestehende Runtime
  ├─ AccountStore / Identity-Linking
  ├─ RuntimeState / Pending Flows
  ├─ WorkingMemory / Account-Memory
  ├─ Built-in Commands
  ├─ LangGraph-Flows fuer komplexe/langlaufende Workflows
  ├─ Pydantic-AI-Subtasks fuer strukturierte Entscheidungen
  ├─ BibliothekarService mit Haystack
  ├─ MCP/FastMCP Tool-Layer, spaeter und streng allowlisted
  └─ LLMRouter
        ├─ OpenAIProvider, Legacy/Premium
        ├─ LiteLLMProvider
        │    ├─ Ollama lokal
        │    ├─ HuggingFace
        │    ├─ Groq
        │    ├─ Gemini
        │    └─ weitere OpenAI-kompatible Provider
        └─ Spezialprovider spaeter optional
```

### Kurzentscheidung

| Bereich | Werkzeug | Rolle |
|---|---|---|
| Provider-Routing | LiteLLM | Einheitlicher Text-LLM-Zugriff fuer OpenAI, Ollama, HF, Groq, Gemini |
| Lokale Modelle | Ollama | Null-Euro-/Privacy-Modus fuer normale Antworten |
| Open-Source-/Remote-Modelle | Hugging Face | Alternative Provider- und Embedding-Quelle |
| Bibliothekar mit vielen Buechern | Haystack | Indexing, Retrieval, Hybrid-Suche, RAG |
| Komplexe Ablaeufe | LangGraph | Orchestrierung, Zustand, lange Workflows |
| Strukturierte LLM-Entscheidungen | Pydantic AI | Intent, Memory-Kandidaten, Reminder, Tool-Planung |
| Tools | MCP/FastMCP | Spaeter: standardisierte, sichere Tool-Schicht |
| Telegram Framework | vorerst keines | Bestehender Adapter bleibt, kein aiogram-Umbau jetzt |

---

## 2. Harte Invarianten

Diese Punkte duerfen durch Codex/Refactoring nicht verletzt werden.

```text
MUSS bleiben:
- python3 -m TeeBotus
- python3 -m TeeBotus --all
- python3 -m TeeBotus --runtime-status --channels telegram
- python3 -m TeeBotus --runtime-status --channels signal
- python3 -m TeeBotus --runtime-status --channels matrix
- TeeBotus/__main__.py delegiert an TeeBotus.bot.main
- TeeBotus/bot.py bleibt Compatibility-Bridge
- Telegram muss weiter ueber den stabilen Poller starten
- Signal/Matrix werden nur additiv angebunden
- Account-Memory wird nicht in Haystack verschoben
- User-Memory bleibt verschluesselt und accountgebunden
- OpenAIClient wird nicht geloescht
- openai_* Settings bleiben als Legacy-Aliase gueltig
```

### Warum OpenAIClient bleiben soll

`OpenAIClient` enthaelt aktuell mehrere Spezialfaehigkeiten:

```text
- Textantworten ueber OpenAI Responses API
- previous_response_id
- Websearch-Tooling
- Reasoning-Einstellungen
- Image Generation
- TTS/Speech
- Audio Transcription
```

Diese Funktionen sind nicht 1:1 providerneutral. Deshalb wird OpenAI zuerst als Provider hinter ein neutrales Interface gelegt, nicht entfernt.

---

## 3. Sicherheits- und Supply-Chain-Regeln

### 3.1 LiteLLM nur kontrolliert installieren

LiteLLM ist fachlich sinnvoll, aber es gab 2026 Berichte ueber kompromittierte PyPI-Versionen `1.82.7` und `1.82.8`. Darum:

```text
- Niemals ungepinnt in Produktion installieren.
- Versionen 1.82.7 und 1.82.8 explizit ausschliessen.
- Lockfile commiten.
- Hashes nutzen, wo moeglich.
- Installation zuerst in isolierter VM/Container testen.
- Danach pip-audit / safety / uv-audit nutzen.
- Keine echten .env Secrets in Testumgebungen.
```

Beispiel fuer Constraints:

```text
litellm!=1.82.7,!=1.82.8
```

Wenn kompromittierte Versionen jemals installiert waren:

```bash
python - <<'PY'
import importlib.metadata as md
for pkg in ["litellm"]:
    try:
        print(pkg, md.version(pkg))
    except md.PackageNotFoundError:
        print(pkg, "not installed")
PY

find .venv -name "*.pth" -print
find ~/.config -path "*sysmon*" -print 2>/dev/null || true
find /tmp -name "pglog" -o -name ".pg_state" 2>/dev/null || true
```

Bei Treffer: Umgebung wegwerfen, Secrets rotieren, Host pruefen.

### 3.2 Secrets

```text
- Keine echten Keys in Repo, Tests oder Issues.
- .env bleibt lokal.
- Langfristig Secret-Service oder systemd EnvironmentFile mit restriktiven Rechten.
- Lokale Services wie Ollama, Qdrant, LiteLLM Proxy nur auf 127.0.0.1 binden.
- MCP-Tools niemals pauschal fuer Nutzer freigeben.
```

Empfohlene Dateirechte:

```bash
chmod 600 .env
chmod -R go-rwx instances/*/data || true
```

---

## 4. Arbeitsbranch und Baseline

### 4.1 Branch anlegen

```bash
cd ~/TeeBotus
git status
git checkout main
git pull --ff-only
git checkout -b feat/llm-router-haystack-bibliothekar
```

### 4.2 Baseline dokumentieren

```bash
python3 --version
git rev-parse HEAD
python3 -m TeeBotus --version
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m TeeBotus --runtime-status --channels signal || true
python3 -m TeeBotus --runtime-status --channels matrix || true
python3 -m pytest -q
```

Wenn kein `pytest` vorhanden:

```bash
python3 -m unittest discover -s tests
```

### 4.3 Backups

Vor jeder Migration:

```bash
mkdir -p backups/$(date +%Y%m%d-%H%M%S)

cp .env backups/$(date +%Y%m%d-%H%M%S)/.env.backup 2>/dev/null || true
tar --exclude='*.log' -czf backups/$(date +%Y%m%d-%H%M%S)/instances-data.tgz instances/*/data 2>/dev/null || true
```

---

## 5. Python-Projekt sauber vorbereiten

Falls noch kein `pyproject.toml` existiert, anlegen. Ziel ist reproduzierbare Installation mit Extras.

### 5.1 Empfohlene Struktur

```toml
[project]
name = "teebotus"
version = "1.4.28"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-cov",
  "ruff",
  "mypy",
  "pip-audit",
]
llm = [
  "litellm!=1.82.7,!=1.82.8",
  "openai",
  "ollama",
]
agents = [
  "pydantic-ai",
  "langgraph",
]
rag = [
  "haystack-ai",
  "qdrant-haystack",
  "sentence-transformers",
  "pypdf",
  "pymupdf",
  "ebooklib",
  "beautifulsoup4",
]
tools = [
  "fastmcp",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

### 5.2 Installation mit uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv .venv --python 3.12
source .venv/bin/activate

uv pip install -e ".[dev]"
python -m pytest -q
```

### 5.3 Danach Extras schrittweise

Nicht alles auf einmal. Erst Provider-Router:

```bash
uv pip install -e ".[dev,llm]"
python -m pytest -q
pip-audit || true
```

Dann Agents:

```bash
uv pip install -e ".[dev,llm,agents]"
python -m pytest -q
pip-audit || true
```

Dann RAG/Bibliothekar:

```bash
uv pip install -e ".[dev,llm,agents,rag]"
python -m pytest -q
pip-audit || true
```

---

## 6. Phase 1: LLM-Interface einziehen

### 6.1 Neue Dateien

```text
TeeBotus/llm/
  __init__.py
  base.py
  capabilities.py
  openai_provider.py
  litellm_provider.py
  router.py
  config.py
```

### 6.2 Neutrale Dataclasses

`TeeBotus/llm/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any


@dataclass(frozen=True)
class LLMResponse:
    text: str
    response_id: str | None = None
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMVoice:
    audio: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class LLMImage:
    data: bytes
    filename: str
    content_type: str


class LLMError(RuntimeError):
    pass


class BaseLLMClient(Protocol):
    def create_reply(self, user_text: str, instructions: object, previous_response_id: str | None = None) -> LLMResponse:
        ...

    def create_voice(self, text: str, instructions: object) -> LLMVoice:
        ...

    def generate_image(self, prompt: str, instructions: object, *, filename: str = "bild.png") -> LLMImage:
        ...

    def transcribe_audio(self, audio: bytes, filename: str, instructions: object, model: str | None = None) -> str:
        ...
```

### 6.3 OpenAIProvider als Wrapper

`OpenAIClient` bleibt, wird aber in `OpenAIProvider` eingebettet.

```text
OpenAIProvider:
- nutzt intern bestehenden OpenAIClient
- mappt OpenAIResponse -> LLMResponse
- mappt OpenAIVoice -> LLMVoice
- mappt OpenAIImage -> LLMImage
- faengt OpenAIAPIError und wirft LLMError oder OpenAIAPIError kompatibel weiter
```

### 6.4 Engine nur minimal anfassen

Aktuell hat `TeeBotusEngine.__init__` `openai_client`.

Ziel:

```python
def __init__(..., llm_client: object | None = None, openai_client: object | None = None, ...):
    self.llm_client = llm_client if llm_client is not None else openai_client
    self.openai_client = self.llm_client  # Legacy-Alias fuer bestehenden Code
```

Danach erst intern Schritt fuer Schritt umbenennen:

```text
self.openai_client -> self.llm_client
_openai_actions -> _llm_actions, aber _openai_actions als Alias behalten
instructions.openai_error -> spaeter instructions.llm_error, vorerst kompatibel lassen
```

### 6.5 Akzeptanzkriterien Phase 1

```text
- Alle bestehenden Tests gruen.
- python3 -m TeeBotus --version funktioniert.
- python3 -m TeeBotus --runtime-status --channels telegram funktioniert.
- Tests fuer __main__/bot.py bleiben unveraendert gueltig.
- OpenAI-Betrieb laeuft wie vorher.
- Keine Aenderung an Memory-Dateien.
```

---

## 7. Phase 2: LiteLLMProvider fuer Textantworten

### 7.1 Providerklasse

`TeeBotus/llm/litellm_provider.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from litellm import completion

from TeeBotus.llm.base import LLMResponse, LLMError


@dataclass(frozen=True)
class LiteLLMSettings:
    model: str
    api_key: str = ""
    api_base: str = ""
    timeout: int = 90
    temperature: float | None = None
    max_tokens: int | None = None


class LiteLLMTextClient:
    def __init__(self, settings: LiteLLMSettings) -> None:
        self.settings = settings

    def create_reply(self, user_text: str, instructions: object, previous_response_id: str | None = None) -> LLMResponse:
        system_text = ""
        if hasattr(instructions, "openai_instructions_text"):
            system_text = instructions.openai_instructions_text()

        messages = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_text})

        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "timeout": self.settings.timeout,
        }
        if self.settings.api_key:
            kwargs["api_key"] = self.settings.api_key
        if self.settings.api_base:
            kwargs["api_base"] = self.settings.api_base
        if self.settings.temperature is not None:
            kwargs["temperature"] = self.settings.temperature
        if self.settings.max_tokens is not None:
            kwargs["max_tokens"] = self.settings.max_tokens

        try:
            response = completion(**kwargs)
        except Exception as exc:
            raise LLMError(f"LiteLLM request failed: {exc}") from exc

        try:
            text = response.choices[0].message.content or ""
        except Exception as exc:
            raise LLMError(f"LiteLLM response shape unsupported: {exc}") from exc

        return LLMResponse(
            text=text.strip(),
            response_id=None,
            provider="litellm",
            model=self.settings.model,
            raw=None,
        )
```

### 7.2 Wichtige Einschraenkung

Bei LiteLLM-Textbetrieb gibt es zuerst **kein** OpenAI-`previous_response_id`.

TeeBotus muss den Verlauf fuer providerneutrale Anbieter selbst bauen:

```text
Kurzfristig:
- previous_response_id fuer LiteLLM ignorieren.
- Memory/WorkingMemory/Bibliothekar-Kontext bleiben im Prompt.
- spaeter: eigene ConversationHistory pro Account/Instanz/Channel.
```

### 7.3 Konfiguration

Neue Env-Variablen:

```bash
TEEBOTUS_LLM_PROVIDER_DEMO=litellm
TEEBOTUS_LLM_MODEL_DEMO=ollama_chat/llama3.1:8b
TEEBOTUS_LLM_BASE_URL_DEMO=http://127.0.0.1:11434
TEEBOTUS_LLM_API_KEY_DEMO=
```

Legacy bleibt:

```bash
OPENAI_API_KEY_DEMO=sk-...
```

Aufloesungsreihenfolge:

```text
1. TEEBOTUS_LLM_PROVIDER_<INSTANCE>_<CHANNEL>_<SLOT>
2. TEEBOTUS_LLM_PROVIDER_<INSTANCE>_<CHANNEL>
3. TEEBOTUS_LLM_PROVIDER_<INSTANCE>
4. TEEBOTUS_LLM_PROVIDER
5. Legacy: openai, wenn OPENAI_API_KEY vorhanden
6. none
```

### 7.4 Bot_Verhalten.md Erweiterung

Neue neutrale Sektion:

```markdown
## LLM
- enabled: true
- provider: litellm
- model: ollama_chat/llama3.1:8b
- base_url: http://127.0.0.1:11434
- max_output_tokens: 700
- timeout_seconds: 120
- temperature: 0.7
```

Legacy-Sektion bleibt gueltig:

```markdown
## OpenAI
- enabled: true
- model: gpt-5.5
```

Regel:

```text
Wenn ## LLM gesetzt ist, hat es Vorrang.
Wenn nur ## OpenAI gesetzt ist, wird Legacy genutzt.
```

### 7.5 Akzeptanzkriterien Phase 2

```text
- Tests fuer BotInstructions: llm_* und openai_* koexistieren.
- OpenAI-Legacy laeuft weiter.
- LiteLLM-Provider kann per Fake/Mock getestet werden.
- Kein echter API-Key in Tests.
- LiteLLM kompromittierte Versionen sind per Constraint ausgeschlossen.
```

---

## 8. Phase 3: Ollama lokal anbinden

### 8.1 Ollama installieren

Fedora:

```bash
curl -fsSL https://ollama.com/install.sh | sh
systemctl --user enable --now ollama || true
```

Wenn systemweiter Dienst genutzt wird:

```bash
sudo systemctl enable --now ollama
```

### 8.2 Modelle ziehen

Start klein:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5:7b
```

Optional fuer Deutsch/mehr Qualitaet je nach Hardware:

```bash
ollama pull qwen2.5:14b
ollama pull mistral-small
```

### 8.3 Lokaler Test

```bash
curl http://127.0.0.1:11434/api/tags
```

LiteLLM-Test:

```python
from litellm import completion

response = completion(
    model="ollama_chat/llama3.1:8b",
    messages=[{"role": "user", "content": "Antworte auf Deutsch in einem Satz."}],
    api_base="http://127.0.0.1:11434",
)
print(response.choices[0].message.content)
```

### 8.4 TeeBotus Instanz konfigurieren

`.env`:

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT=litellm
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT=ollama_chat/llama3.1:8b
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT=http://127.0.0.1:11434
```

`instances/Depressionsbot/Bot_Verhalten.md`:

```markdown
## LLM
- enabled: true
- provider: litellm
- model: ollama_chat/llama3.1:8b
- base_url: http://127.0.0.1:11434
- max_output_tokens: 700
- timeout_seconds: 180
```

### 8.5 Fallback-Strategie

```text
cheap/private:
  ollama_chat/llama3.1:8b

better:
  groq/...
  gemini/...
  openai/...

fallback:
  wenn lokales Modell Timeout/Fehler -> optional Remote-Provider
```

Noch nicht in Phase 3 automatisch fallbacken. Erst manuell stabilisieren.

---

## 9. Phase 4: Hugging Face, Groq, Gemini ueber LiteLLM

### 9.1 Providerprofile

`config/llm_profiles.yaml`:

```yaml
profiles:
  local_ollama:
    provider: litellm
    model: ollama_chat/llama3.1:8b
    base_url: http://127.0.0.1:11434
    api_key_env: ""

  hf_mistral:
    provider: litellm
    model: huggingface/mistralai/Mistral-7B-Instruct-v0.3
    api_key_env: HUGGINGFACE_API_KEY

  groq_fast:
    provider: litellm
    model: groq/llama-3.1-8b-instant
    api_key_env: GROQ_API_KEY

  gemini_flash:
    provider: litellm
    model: gemini/gemini-2.5-flash
    api_key_env: GEMINI_API_KEY

  openai_premium:
    provider: openai
    model: gpt-5.5
    api_key_env: OPENAI_API_KEY
```

### 9.2 Router-Regeln

```yaml
routing:
  default_profile: local_ollama

  purposes:
    normal_chat:
      profile: local_ollama
      fallback: gemini_flash

    hard_reasoning:
      profile: openai_premium
      fallback: gemini_flash

    cheap_fast:
      profile: groq_fast
      fallback: local_ollama

    private:
      profile: local_ollama
      fallback: null

    bibliothekar_answer:
      profile: gemini_flash
      fallback: local_ollama
```

### 9.3 Keine automatischen Kostenfallen

```text
- Remote-Fallback standardmaessig aus.
- Pro Instanz explizit aktivieren.
- Spaeter Kostenzaehler pro Account/Instanz.
- Fehlerausgabe soll Provider nennen, aber keine Secrets.
```

---

## 10. Phase 5: Haystack-Bibliothekar

### 10.1 Rolle des Bibliothekars

Haystack ist nicht fuer persoenliche User-Memorys da. Haystack ist fuer grosse Wissensbestaende:

```text
- Buecher
- PDFs
- EPUBs
- Markdown
- wissenschaftliche Quellen
- interne Regelwerke
- Nachschlagewerke
```

TeeBotus-Memory bleibt getrennt:

```text
AccountStore:
  - Identitaeten
  - Account-Secret-Verifier
  - User-Memory
  - Gewohnheiten
  - Aktivitaetsprofil

Bibliothekar/Haystack:
  - Dokumente
  - Chunks
  - Metadaten
  - Retrieval-Index
  - Quellenangaben
```

### 10.2 Neue Struktur

```text
TeeBotus/bibliothekar/
  __init__.py
  config.py
  schema.py
  converters.py
  chunking.py
  index_pipeline.py
  query_pipeline.py
  service.py
  citations.py
  cli.py

library/
  inbox/
  books/
  processed/
  rejected/

data/
  bibliothekar/
    manifest.sqlite
    qdrant/
    exports/
```

### 10.3 Document-Metadaten

Jeder Chunk braucht stabile Metadaten:

```yaml
source_id: sha256:<file_hash>
chunk_id: <source_id>:<page>:<chunk_index>
title: "Buchtitel"
author: "Autor"
file_path: "library/books/..."
file_sha256: "..."
file_type: "pdf|epub|md|txt"
language: "de|en|unknown"
page_start: 12
page_end: 13
chapter: "Kapitel 2"
section: "Unterabschnitt"
license: "unknown/private/public"
ingested_at: "2026-06-15T..."
chunk_index: 42
```

### 10.4 Chunking-Regeln

```text
Ziel:
- 800 bis 1200 Token pro Chunk
- 100 bis 150 Token Overlap
- Kapitel-/Abschnittsgrenzen respektieren
- Seitenzahlen erhalten
- Tabellen separat markieren
- Fussnoten nicht verlieren
- Dokumenttitel und Kapitel als Metadaten behalten
```

### 10.5 Qdrant fuer viele Buecher

Qdrant lokal per Podman:

```bash
podman volume create teebotus-qdrant

podman run -d \
  --name teebotus-qdrant \
  --restart=unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -v teebotus-qdrant:/qdrant/storage \
  qdrant/qdrant:latest
```

Produktiver: Container-Tag pinnen oder Digest nutzen, nicht dauerhaft `latest`.

Healthcheck:

```bash
curl http://127.0.0.1:6333/collections
```

### 10.6 Haystack Dependencies

```bash
uv pip install -e ".[rag]"
```

Bei fehlendem Qdrant-Paket:

```bash
uv pip install haystack-ai qdrant-haystack sentence-transformers
```

### 10.7 Embeddings

Start lokal:

```text
Embedding-Modell Kandidaten:
- intfloat/multilingual-e5-small
- intfloat/multilingual-e5-base
- BAAI/bge-m3
```

Regel:

```text
- small/base fuer CPU-Test
- groessere Modelle erst nach Benchmark
- Embeddings nicht mit Chat-Provider vermischen
- Modellname in Manifest speichern
```

### 10.8 Indexing CLI

Zielbefehle:

```bash
python3 -m TeeBotus.bibliothekar index \
  --source library/inbox \
  --collection teebotus_books \
  --manifest data/bibliothekar/manifest.sqlite \
  --embedding-model intfloat/multilingual-e5-small

python3 -m TeeBotus.bibliothekar status

python3 -m TeeBotus.bibliothekar query \
  "Was sagt Buch X zu ADHS und Arbeitsgedaechtnis?" \
  --top-k 8
```

### 10.9 Query Pipeline

Minimal:

```text
Query
  -> Query Embedder
  -> Qdrant Embedding Retriever
  -> optional BM25/Keyword Retriever
  -> Joiner/Reranker
  -> Citation Builder
  -> Kontextblock fuer TeeBotus LLM
```

Spaeter hybrid:

```text
Query
  ├─ BM25 Retriever
  ├─ Dense Retriever
  └─ Metadata Filter
       ↓
    Joiner
       ↓
    Reranker
       ↓
    Top-K Chunks mit Zitaten
```

### 10.10 Antwortregeln fuer Bibliothekar

```text
- Keine Behauptung ohne Quelle, wenn Bibliothekar-Modus aktiv ist.
- Jede wichtige Aussage mit Buch/Seite/Chunk belegen.
- Wenn keine Stelle gefunden wurde: "Ich finde dazu in der Bibliothek gerade keine belastbare Stelle."
- Zitate kurz halten.
- User-Memory niemals in den Haystack-Index schreiben.
- Private Dokumente als private markieren.
```

### 10.11 Integration in TeeBotusEngine

In `_openai_actions` bzw. spaeter `_llm_actions` wird vor dem LLM-Aufruf Bibliothekar-Kontext gebaut.

Aktuell gibt es bereits Logik fuer Bibliothekar-Kontext. Ziel ist, diese Quelle von einfachem Store auf HaystackService umzustellen:

```text
_build_bibliothekar_context(...)
  -> BibliothekarService.search(query, filters, top_k)
  -> formatierte Quellenkontexte
```

Feature-Flag:

```markdown
## Bibliothekar
- enabled: true
- backend: haystack
- max_chunks: 5
- max_prompt_chars: 5000
- max_quote_chars: 900
- require_citations: true
```

### 10.12 Akzeptanzkriterien Phase 5

```text
- Indexing von 3 Testdokumenten funktioniert.
- Query liefert Chunks mit Titel, Datei, Seite, Score.
- TeeBotus kann Bibliothekar-Kontext in Antwortprompt aufnehmen.
- Keine User-Memorys im Haystack-Index.
- Rebuild des Index ist reproduzierbar.
- Manifest erkennt unveraenderte Dateien und indexiert sie nicht erneut.
```

---

## 11. Phase 6: Pydantic AI fuer strukturierte Subtasks

Pydantic AI ist nicht der Bot-Kern. Es ist der strukturierte Entscheider.

### 11.1 Geeignete Aufgaben

```text
- Intent-Erkennung
- Memory-Kandidaten extrahieren
- Reminder aus natuerlicher Sprache erkennen
- YouTube-Optionen parsen
- Tool-Plan validieren
- Sicherheitsentscheidung: darf Tool X laufen?
```

### 11.2 Beispielschemas

`TeeBotus/ai_structures/schemas.py`:

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
        "unknown",
    ]
    confidence: float = Field(ge=0, le=1)
    reason_short: str


class MemoryCandidate(BaseModel):
    should_store: bool
    memory_type: Literal["preference", "profile", "habit", "project", "relationship", "none"]
    text: str
    sensitivity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)


class ReminderDecision(BaseModel):
    should_create: bool
    text: str
    datetime_iso: str | None = None
    recurrence: str | None = None
    confidence: float = Field(ge=0, le=1)
```

### 11.3 Teststrategie

```text
- Pydantic AI zuerst mit TestModel/FakeModel testen.
- Keine echten Provider in Unit-Tests.
- Schwellenwerte:
  confidence < 0.70 -> klassische Parser/Follow-up
  high sensitivity -> nicht automatisch speichern
```

### 11.4 Integration

```text
TeeBotusEngine
  -> klassischer Parser zuerst fuer Slash-Commands
  -> Pydantic AI nur bei unklarer natuerlicher Sprache
  -> Ergebnis validieren
  -> niemals blind Tool ausfuehren
```

---

## 12. Phase 7: LangGraph bewusst nutzen

LangGraph ist bereits konzeptionell Teil eures Systems bzw. Zielsystems. Es soll die Engine nicht ersetzen, sondern komplexe Workflows kapseln.

### 12.1 Geeignete Flows

```text
- Proactive-Agent:
  observe -> plan -> select due -> generate -> safety -> dispatch -> record

- Bibliothekar Deep Query:
  classify -> retrieve -> rerank -> answer -> citation_check -> fallback

- Codex Task:
  authorize -> plan -> sandbox -> execute -> summarize -> approval

- YouTube Pipeline:
  detect -> transcript -> local transcribe -> summarize -> memory decision

- Account-Linking Security:
  login -> notify old identities -> grace period -> WTF rollback -> rotate secret
```

### 12.2 Nicht geeignet

```text
- /ping
- /help
- /status
- simple exact text replies
- normaler Chat ohne Spezialworkflow
```

### 12.3 Minimaler Graph-Wrapper

```text
TeeBotus/runtime/graphs/
  __init__.py
  proactive_graph.py
  bibliothekar_graph.py
  codex_graph.py
```

LangGraph nur laden, wenn Feature aktiv:

```python
try:
    import langgraph
except ImportError:
    langgraph = None
```

### 12.4 Akzeptanzkriterien Phase 7

```text
- Normale Botantworten laufen ohne LangGraph.
- LangGraph-Flow kann isoliert getestet werden.
- State serialisierbar.
- Fehler setzen keine halbfertigen Memory-Eintraege.
- Human-in-the-loop Flags fuer riskante Tools vorhanden.
```

---

## 13. Phase 8: MCP/FastMCP spaeter

MCP ist sinnvoll, aber gefaehrlich, wenn falsch eingebaut.

### 13.1 Erlaubte erste Tools

```yaml
mcp_tools:
  memory.search:
    enabled: true
    read_only: true

  bibliothekar.search:
    enabled: true
    read_only: true

  youtube.transcribe:
    enabled: true
    requires_confirmation: false

  export.account:
    enabled: true
    private_chat_only: true

  codex.exec:
    enabled: false
    requires_admin: true
    requires_confirmation: true
    sandbox_required: true
```

### 13.2 Verboten am Anfang

```text
- freie Shell
- Dateisystem ohne Pfad-Allowlist
- Netzwerkscans
- Secret-Ausgabe
- Schreibzugriff auf .env
- Loeschen von Memory ohne explizite Userbestaetigung
```

---

## 14. Runtime-Status erweitern

`python3 -m TeeBotus --runtime-status` soll zusaetzlich melden:

```text
llm=Depressionsbot/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b status=configured base_url=127.0.0.1:11434
llm=Depressionsbot/telegram:1 provider=openai model=gpt-5.5 status=missing_key
bibliothekar=Depressionsbot backend=haystack document_store=qdrant status=reachable collections=1 documents=12345
ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b,qwen2.5:7b
```

Tests:

```text
tests/test_runtime_status_llm.py
tests/test_runtime_status_bibliothekar.py
```

---

## 15. Systemd-Beispiele

### 15.1 Ollama User-Service pruefen

```bash
systemctl --user status ollama
```

### 15.2 Qdrant Podman Service

```bash
podman generate systemd --new --files --name teebotus-qdrant
mkdir -p ~/.config/systemd/user
mv container-teebotus-qdrant.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now container-teebotus-qdrant.service
```

### 15.3 TeeBotus Service mit EnvFile

`~/.config/systemd/user/teebotus.service`:

```ini
[Unit]
Description=TeeBotus multi-channel bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/TeeBotus
EnvironmentFile=%h/TeeBotus/.env
ExecStart=%h/TeeBotus/.venv/bin/python -m TeeBotus --all --channels telegram,signal,matrix
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
```

Start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now teebotus.service
journalctl --user -u teebotus.service -f
```

---

## 16. Testplan

### 16.1 Unit Tests

```bash
python -m pytest -q tests/test_entrypoint_compatibility.py
python -m pytest -q tests/test_runtime_config.py
python -m pytest -q tests/test_openai_client.py
python -m pytest -q tests/test_engine_identity_flows.py
```

Neue Tests:

```text
tests/test_llm_base.py
tests/test_llm_router.py
tests/test_litellm_provider.py
tests/test_llm_config.py
tests/test_bibliothekar_haystack_schema.py
tests/test_bibliothekar_citations.py
tests/test_pydantic_decisions.py
```

### 16.2 Provider-Fake

Kein echter Provider in Unit-Tests:

```python
class FakeLLMClient:
    def create_reply(self, user_text, instructions, previous_response_id=None):
        return LLMResponse(text="fake reply", response_id="fake")
```

### 16.3 Integrationstests lokal

```bash
# Ollama muss laufen
curl http://127.0.0.1:11434/api/tags

TEEBOTUS_LLM_PROVIDER_DEMO=litellm \
TEEBOTUS_LLM_MODEL_DEMO=ollama_chat/llama3.1:8b \
TEEBOTUS_LLM_BASE_URL_DEMO=http://127.0.0.1:11434 \
python3 -m TeeBotus --runtime-status --channels telegram
```

### 16.4 Bibliothekar-Testdaten

```text
tests/fixtures/books/
  short_adhs.md
  short_attachment.md
  short_linux.md
```

Testfragen:

```text
- "Was sagt die Quelle zu ADHS und Arbeitsgedaechtnis?"
- "Welche Stelle nennt Bindungsangst?"
- "Frage nach etwas, das nicht vorkommt."
```

Erwartung:

```text
- passende Quelle gefunden
- Seiten/Chunk-ID vorhanden
- bei Nichtfund ehrliche Nichtfund-Antwort
```

---

## 17. Rollback-Plan

### 17.1 Sofort-Rollback ohne Git-Revert

In `.env`:

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT=openai
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT=
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT=
```

Oder LLM komplett aus:

```bash
TEEBOTUS_LLM_ENABLED_DEPRESSIONSBOT=false
```

Legacy OpenAI aktiv lassen:

```bash
OPENAI_API_KEY_DEPRESSIONSBOT=sk-...
```

### 17.2 Git-Rollback

```bash
git checkout main
python3 -m TeeBotus --runtime-status --channels telegram
```

### 17.3 Daten-Rollback

```bash
systemctl --user stop teebotus.service || true
tar -xzf backups/<timestamp>/instances-data.tgz -C .
cp backups/<timestamp>/.env.backup .env
systemctl --user start teebotus.service || true
```

Haystack/Qdrant Index kann jederzeit neu gebaut werden, weil er aus Dokumenten + Manifest reproduzierbar sein soll.

---

## 18. Codex-Arbeitsauftraege

### Auftrag 1: LLM-Interface

```text
Erstelle TeeBotus/llm/base.py, capabilities.py, openai_provider.py und router.py.
Baue OpenAIClient als kompatiblen Provider ein.
Aendere TeeBotusEngine minimal so, dass llm_client genutzt wird, openai_client aber als Alias funktioniert.
Alle bestehenden Tests muessen gruen bleiben.
Keine OpenAI-Funktionen entfernen.
```

Akzeptanz:

```text
python3 -m pytest -q tests/test_entrypoint_compatibility.py tests/test_openai_client.py
python3 -m TeeBotus --version
```

### Auftrag 2: LLM-Konfiguration

```text
Ergaenze BotInstructions um llm_* Felder.
openai_* bleibt Legacy.
Ergaenze RuntimeConfig um provider/model/base_url/api_key_env.
Implementiere Aufloesung aus TEEBOTUS_LLM_* mit OpenAI-Fallback.
Ergaenze Tests.
```

Akzeptanz:

```text
python3 -m pytest -q tests/test_runtime_config.py tests/test_llm_config.py
```

### Auftrag 3: LiteLLMProvider

```text
Implementiere LiteLLMTextClient.
Installationsconstraints muessen litellm!=1.82.7,!=1.82.8 enthalten.
Keine echten Provider in Unit-Tests.
```

Akzeptanz:

```text
python3 -m pytest -q tests/test_litellm_provider.py
pip-audit || true
```

### Auftrag 4: Ollama-Profil

```text
Ergaenze Beispielkonfiguration fuer Ollama.
Runtime-Status soll Ollama base_url anzeigen.
Integrationstest optional, wenn Ollama lokal laeuft.
```

Akzeptanz:

```text
python3 -m TeeBotus --runtime-status --channels telegram
```

### Auftrag 5: Bibliothekar/Haystack Grundgeruest

```text
Erstelle TeeBotus/bibliothekar Paket.
Implementiere Dokument-Metadaten, Manifest, Chunking und Query-Service.
Noch keine grosse UI.
Erst Markdown/TXT, danach PDF/EPUB.
```

Akzeptanz:

```text
python3 -m TeeBotus.bibliothekar index --source tests/fixtures/books --dry-run
python3 -m TeeBotus.bibliothekar query "Testfrage" --top-k 3
python3 -m pytest -q tests/test_bibliothekar_*.py
```

### Auftrag 6: Haystack + Qdrant

```text
QdrantDocumentStore anbinden.
Indexing Pipeline mit Converter, Cleaner, Splitter, Embedder, Writer.
Query Pipeline mit Retriever und Citation Builder.
```

Akzeptanz:

```text
curl http://127.0.0.1:6333/collections
python3 -m TeeBotus.bibliothekar status
```

### Auftrag 7: Pydantic AI Subtasks

```text
Implementiere strukturierte IntentDecision, MemoryCandidate, ReminderDecision.
Nutze Fake/TestModel in Unit-Tests.
In Engine nur fuer unklare natuerliche Sprache aktivieren.
Slash-Commands bleiben klassische Parser.
```

Akzeptanz:

```text
python3 -m pytest -q tests/test_pydantic_decisions.py
```

### Auftrag 8: LangGraph-Flows

```text
Erstelle TeeBotus/runtime/graphs.
Migriere nur einen geeigneten Flow als Pilot: Bibliothekar Deep Query oder Proactive-Agent.
Normale Chatantworten duerfen nicht von LangGraph abhaengen.
```

Akzeptanz:

```text
python3 -m pytest -q tests/test_graphs_*.py
```

### Auftrag 9: Runtime-Status komplettieren

```text
Erweitere --runtime-status um:
- LLM Provider
- Modell
- base_url ohne Secrets
- Ollama Reachability
- Bibliothekar Backend
- Qdrant Status
```

Akzeptanz:

```text
python3 -m TeeBotus --runtime-status --channels telegram
```

### Auftrag 10: Dokumentation

```text
README aktualisieren:
- Provider-Router
- Ollama Quickstart
- HuggingFace/Groq/Gemini Profile
- Haystack Bibliothekar
- Security Notes
- Rollback
- Datenschutz DE/EN
```

Akzeptanz:

```text
README enthaelt keine Secrets.
README enthaelt klare Warnung zu lokalen/remote Providern.
README erklaert, dass Account-Memory nicht in Haystack liegt.
```

---

## 19. Empfohlene Reihenfolge

```text
Tag 1:
- Branch, Baseline, pyproject/uv/dev extras
- Tests gruen

Tag 2:
- LLM-Interface + OpenAIProvider Wrapper
- Keine Funktionsaenderung

Tag 3:
- llm_* Config + Legacy-Aliase
- Runtime-Status erweitert

Tag 4:
- LiteLLMProvider Text
- Ollama lokaler Test

Tag 5:
- Providerprofile fuer Ollama/HF/Groq/Gemini
- Kein Auto-Fallback ohne Flag

Tag 6-7:
- Haystack Bibliothekar Grundgeruest
- Markdown/TXT indexing
- Qdrant lokal

Tag 8:
- PDF/EPUB ingestion
- Citation Builder

Tag 9:
- Pydantic AI fuer Intent/Memory/Reminder

Tag 10+:
- LangGraph-Pilotflow
- MCP/FastMCP nur read-only und allowlisted
```

---

## 20. Definition of Done

```text
- python3 -m TeeBotus funktioniert.
- python3 -m TeeBotus --all funktioniert.
- Telegram startet wie vorher.
- Signal/Matrix Runtime-Status bleibt intakt.
- OpenAI Legacy funktioniert.
- Ollama kann als LLM-Provider genutzt werden.
- HuggingFace/Groq/Gemini sind als Profile vorbereitet.
- Bibliothekar kann Testdokumente indexieren und mit Quellen abrufen.
- Account-Memory bleibt getrennt und verschluesselt.
- Keine echten Secrets im Repo.
- Tests fuer EntryPoint, RuntimeConfig, LLMRouter, Bibliothekar und Pydantic-Subtasks existieren.
- Rollback ist dokumentiert und ohne Datenverlust moeglich.
```

---

## 21. Referenzlinks

- LiteLLM Dokumentation: https://docs.litellm.ai/
- LiteLLM Ollama Provider: https://docs.litellm.ai/docs/providers/ollama
- LiteLLM Hugging Face Provider: https://docs.litellm.ai/docs/providers/huggingface
- Haystack Pipelines: https://docs.haystack.deepset.ai/docs/pipelines
- Haystack Document Stores: https://docs.haystack.deepset.ai/docs/document-store
- Haystack Retrievers: https://docs.haystack.deepset.ai/docs/retrievers
- Pydantic AI: https://pydantic.dev/docs/ai/overview/
- Pydantic AI Models: https://pydantic.dev/docs/ai/models/overview/
- LangGraph Overview: https://docs.langchain.com/oss/python/langgraph/overview
- signal-cli: https://github.com/AsamK/signal-cli
