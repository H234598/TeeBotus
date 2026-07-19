# TeeBotus — detaillierter Installations- und Migrationsplan

**Ziel:** TeeBotus so erweitern, dass OpenAI, Ollama, Hugging Face, Groq, Gemini und weitere Provider austauschbar nutzbar werden; der Bibliothekar soll mit vielen Büchern/Dokumenten sauber über Haystack arbeiten; LangGraph bleibt für lange Workflows zuständig; Pydantic AI wird für strukturierte Entscheidungen genutzt.

**Version:** v2  
**Datum:** 2026-06-15  
**Zielsystem:** Fedora/Linux, Python 3.11+ / 3.12 empfohlen  
**Repo:** `H234598/TeeBotus`  
**Grundsatz:** Keine Big-Bang-Migration. Erst stabilisieren, dann Provider abstrahieren, dann RAG/Bibliothekar, dann Agenten-Subtasks.

## Implementierungsstand

Stand: 2026-06-19

Quelle:

- `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming/Plan2.md` ist in `docs/Plan2.md` integriert.
- Download-SHA256: `b0e429bef5398e6cf067693f5390486ccb137f3ebef9770cb0509c585cd832f0`
- Der Dokumentkoerper folgt dem aktuellen Download-Stand; dieser Kopf fuehrt den Repo-Status analog zu `docs/Codex_Outbox_History_Plan.md`.

Umgesetzt:

- Plan2 liegt versioniert unter `docs/` und ist der lebende Migrationsplan fuer providerneutrale LLMs, Bibliothekar/RAG, Agenten-Subtasks und Benchmarks.
- Der Zusatzauftrag "Baue valide Benchmarktests fuer alles" bleibt am Ende des Plans als verbindlicher Benchmark-Abschnitt dokumentiert.
- Fuer bereits umgesetzte Detailarbeit sind Code, Tests, Runtime-Status, Benchmarks und spezifischere Plaene die autoritative Quelle.

Offen:

- Neue `/Downloads/Plan2.md`-Aenderungen sollen kuenftig gemerged, nicht blind ueber gepflegte Repo-Ergaenzungen kopiert werden.
- Der tatsaechliche Umsetzungsstand bleibt gegen Code, Tests, Runtime-Status und die spezifischeren Plan3-/Codex-Outbox-Dokumente zu pruefen.

---

## 0. Kurzfassung für Codex

```text
Nicht den Bot neu bauen.
Nicht TeeBotusEngine ersetzen.
Nicht OpenAIClient löschen.
Nicht Account-Memory in Haystack verschieben.

Stattdessen:
1. LLM-Interface einziehen.
2. OpenAIClient als Legacy/Premium-Provider wrappen.
3. LiteLLMProvider für Text-Chat hinzufügen.
4. Ollama lokal als erstes nicht-OpenAI-Backend testen.
5. HuggingFace/Groq/Gemini über LiteLLM-Profile ergänzen.
6. Haystack als separaten Bibliothekar-RAG-Dienst anbauen.
7. Pydantic AI nur für strukturierte Subtasks einsetzen.
8. LangGraph nur für lange/mehrstufige Workflows einsetzen.
9. MCP/FastMCP später, nur allowlisted und sicher.
10. Tests und Rollback vor jeder Stufe.
```

---

## 1. Ausgangslage

TeeBotus hat bereits wichtige Grundlagen:

```text
- python3 -m TeeBotus
- python3 -m TeeBotus --all
- TeeBotus/__main__.py als Paket-Entry-Point
- TeeBotus/bot.py als stabile Compatibility-Bridge
- Telegram-Adapter
- Signal-Runtime
- Matrix-Runtime
- channel-neutrale Engine
- Account-Linking über /register und /login
- AccountStore / verschlüsselter Account-Memory
- WorkingMemory / Bibliothekar-ähnliche Kontexte
- OpenAIClient für Responses, Images, Voice und Transcription
- Tests für Entry-Point, Runtime, OpenAIClient, Signal/Matrix usw.
```

Der Engpass ist nicht mehr die Bot-Architektur, sondern die **Provider-Kopplung**:

```text
Aktuell:
TeeBotusEngine → openai_client → OpenAI Responses API

Ziel:
TeeBotusEngine → llm_client / llm_router
  ├─ OpenAIProvider
  ├─ LiteLLMProvider
  ├─ Ollama über LiteLLM
  ├─ HuggingFace über LiteLLM
  ├─ Groq über LiteLLM
  ├─ Gemini über LiteLLM
  └─ spätere Spezialprovider
```

---

## 2. Architekturentscheidung

### 2.1 Rollen der Frameworks

| Komponente | Aufgabe | Einordnung |
|---|---|---|
| TeeBotusEngine | Bot-Kern, Account-Flows, Commands, Memory-Kontext | bleibt |
| LangGraph | lange zustandsbehaftete Workflows | ergänzen, nicht überall |
| LiteLLM | Provider-Routing | zuerst einbauen |
| Ollama | lokale Modelle | zuerst testen |
| Hugging Face | offene Modelle, Inference, Embeddings | über LiteLLM und später für RAG |
| Haystack | viele Bücher/Dokumente, RAG, Retriever, Pipelines | Bibliothekar-Kern |
| Pydantic AI | strukturierte LLM-Outputs | Subtasks |
| MCP/FastMCP | Tool-Schicht | später, streng begrenzt |
| aiogram | Telegram-Framework | jetzt nicht nötig |
| CrewAI/AutoGen/Semantic Kernel | Multi-Agenten | jetzt nicht in den Kern |

### 2.2 Zielbild

```text
Telegram / Signal / Matrix
        │
        ▼
IncomingEvent
        │
        ▼
TeeBotusEngine
        ├─ Slash Commands
        ├─ Account-/Identity-Flows
        ├─ Datenschutz-/Memory-Flows
        ├─ YouTube / Voice / Export
        ├─ LangGraph-Workflow optional
        ├─ Pydantic AI Decision optional
        ├─ BibliothekarService
        │     └─ Haystack
        │          ├─ DocumentStore
        │          ├─ Retriever
        │          ├─ Reranker
        │          └─ Citation Builder
        └─ LLMRouter
              ├─ OpenAIProvider
              └─ LiteLLMProvider
                    ├─ Ollama
                    ├─ HuggingFace
                    ├─ Groq
                    └─ Gemini
```

---

## 3. Harte Invarianten

Diese Punkte sind nicht verhandelbar.

```text
MUSS erhalten bleiben:
- python3 -m TeeBotus
- python3 -m TeeBotus --all
- python3 -m TeeBotus --runtime-status --channels telegram
- python3 -m TeeBotus --runtime-status --channels signal
- python3 -m TeeBotus --runtime-status --channels matrix
- TeeBotus/__main__.py delegiert an TeeBotus.bot.main
- TeeBotus/bot.py bleibt öffentlicher/stabiler Entry-Point
- Telegram, Signal und Matrix laufen als gleichwertige additive Runtime-Slots
- Telegram-Long-Polling bleibt nur ein austauschbarer Telegram-Transport, keine Kernarchitektur
- Account-Memory bleibt verschlüsselt
- Account-Memory wird nicht in Haystack indexiert
- OpenAIClient bleibt erhalten
- openai_* Konfiguration bleibt als Legacy gültig
- echte Secrets landen niemals im Repo
```

---

## 4. Sicherheitsnotizen

### 4.1 LiteLLM Supply-Chain-Schutz

LiteLLM ist fachlich der richtige Provider-Router, aber externe Abhängigkeiten müssen sauber kontrolliert werden. Für LiteLLM wurden im März 2026 kompromittierte PyPI-Versionen `1.82.7` und `1.82.8` berichtet. Diese Versionen dürfen nicht installiert werden.

Empfohlene Constraint-Regel:

```text
litellm!=1.82.7,!=1.82.8
```

Noch besser:

```text
- genaue Version pinnen
- Lockfile commiten
- pip-audit oder uv audit laufen lassen
- keine echten Secrets in Test-VMs verwenden
- nach Erstinstallation Site-Packages grob prüfen
```

Prüfung:

```bash
python - <<'PY'
import importlib.metadata as md

for package in ["litellm", "haystack-ai", "pydantic-ai", "langgraph"]:
    try:
        print(package, md.version(package))
    except md.PackageNotFoundError:
        print(package, "not installed")
PY

find .venv -name "*.pth" -print
```

Wenn kompromittierte Versionen jemals installiert waren:

```text
- virtuelle Umgebung löschen
- Host prüfen
- alle betroffenen API-Keys/Token rotieren
- .env neu erzeugen
- keine alte venv weiterverwenden
```

### 4.2 Secrets

```text
- .env bleibt lokal.
- .env wird nicht committed.
- chmod 600 .env
- systemd EnvironmentFile nur mit restriktiven Rechten.
- keine echten Provider-Keys in Tests.
- Runtime-Status darf niemals API-Keys ausgeben.
```

```bash
chmod 600 .env
chmod -R go-rwx instances/*/data 2>/dev/null || true
```

### 4.3 Lokale Dienste

```text
- Ollama nur auf 127.0.0.1 binden.
- Qdrant nur auf 127.0.0.1 binden.
- LiteLLM Proxy, falls genutzt, nur lokal oder mit Auth.
- MCP-Tools niemals öffentlich freigeben.
```

---

## 5. Arbeitsbranch und Baseline

### 5.1 Branch

```bash
cd ~/TeeBotus
git status
git checkout main
git pull --ff-only
git checkout -b feat/provider-router-haystack-bibliothekar
```

### 5.2 Baseline ausführen

```bash
python3 --version
git rev-parse HEAD

python3 -m TeeBotus --version
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m TeeBotus --runtime-status --channels signal || true
python3 -m TeeBotus --runtime-status --channels matrix || true

python3 -m pytest -q
```

Fallback, falls `pytest` fehlt:

```bash
python3 -m unittest discover -s tests
```

### 5.3 Backup

```bash
mkdir -p backups/$(date +%Y%m%d-%H%M%S)

cp .env backups/$(date +%Y%m%d-%H%M%S)/.env.backup 2>/dev/null || true

tar \
  --exclude='*.log' \
  --exclude='*.tmp' \
  -czf backups/$(date +%Y%m%d-%H%M%S)/instances-data.tgz \
  instances/*/data 2>/dev/null || true
```

---

Nicht:
  TeeBotus/bibliothekar komplett neu neben runtime/bibliothekar.py bauen
Sondern:
  bestehenden BibliothekarStore als Legacy/Local Backend behalten
  + HaystackBibliothekarBackend ergänzen
  + gemeinsames BibliothekarService-Interface einziehen
^-- Absatz drüber, gilt für Zeug drunter  --v

## 6. Python-Projekt reproduzierbar machen

### 6.1 Ziel

Derzeit wirkt TeeBotus bewusst dependency-arm. Das bleibt gut. Neue schwere Komponenten kommen als **Extras**, nicht als Pflichtabhängigkeit.

```text
Core:
- läuft möglichst ohne große Frameworks

Extras:
- llm
- rag
- agents
- tools
- dev
```

### 6.2 pyproject.toml ergänzen

```toml
[project]
name = "teebotus"
dynamic = ["version"]
requires-python = ">=3.11"

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-cov",
  "ruff",
  "mypy",
  "pip-audit",
]

llm = [
  "litellm==1.89.2",
  "openai==2.43.0; python_version < '3.14'",
  "openai==2.30.0; python_version >= '3.14'",
  "ollama==0.6.2",
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

agents = [
  "pydantic-ai",
  "langgraph",
]

tools = [
  "fastmcp",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

### 6.3 uv verwenden

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv .venv --python 3.12
source .venv/bin/activate

uv pip install -e ".[dev]"
python -m pytest -q
```

### 6.4 Extras stufenweise installieren

Provider:

```bash
uv pip install -e ".[dev,llm]"
python -m pytest -q
pip-audit || true
```

RAG:

```bash
uv pip install -e ".[dev,llm,rag]"
python -m pytest -q
pip-audit || true
```

Agents:

```bash
uv pip install -e ".[dev,llm,rag,agents]"
python -m pytest -q
pip-audit || true
```

Tools erst später:

```bash
uv pip install -e ".[dev,llm,rag,agents,tools]"
python -m pytest -q
pip-audit || true
```

---

## 7. Phase 1 — neutrales LLM-Interface

### 7.1 Neue Paketstruktur

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

### 7.2 base.py

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
    def create_reply(
        self,
        user_text: str,
        instructions: object,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        ...

    def create_voice(self, text: str, instructions: object) -> LLMVoice:
        ...

    def generate_image(
        self,
        prompt: str,
        instructions: object,
        *,
        filename: str = "bild.png",
    ) -> LLMImage:
        ...

    def transcribe_audio(
        self,
        audio: bytes,
        filename: str,
        instructions: object,
        model: str | None = None,
    ) -> str:
        ...
```

### 7.3 capabilities.py

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCapabilities:
    text: bool = True
    streaming: bool = False
    previous_response_id: bool = False
    tools: bool = False
    web_search: bool = False
    images: bool = False
    speech: bool = False
    transcription: bool = False
    json_schema: bool = False
```

### 7.4 OpenAIProvider

`OpenAIClient` bleibt unverändert oder nahezu unverändert. Dazu kommt ein Wrapper:

```python
from TeeBotus.llm.base import LLMResponse, LLMVoice, LLMImage, LLMError
from TeeBotus.openai_client import OpenAIClient, OpenAIAPIError


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, client: OpenAIClient) -> None:
        self.client = client

    def create_reply(self, user_text, instructions, previous_response_id=None):
        try:
            response = self.client.create_reply(user_text, instructions, previous_response_id)
        except OpenAIAPIError as exc:
            raise LLMError(str(exc)) from exc

        return LLMResponse(
            text=response.text,
            response_id=response.response_id,
            provider="openai",
            model=getattr(instructions, "openai_model", ""),
            raw=None,
        )

    def create_voice(self, text, instructions):
        try:
            voice = self.client.create_voice(text, instructions)
        except OpenAIAPIError as exc:
            raise LLMError(str(exc)) from exc
        return LLMVoice(voice.audio, voice.filename, voice.content_type)

    def generate_image(self, prompt, instructions, *, filename="bild.png"):
        try:
            image = self.client.generate_image(prompt, instructions, filename=filename)
        except OpenAIAPIError as exc:
            raise LLMError(str(exc)) from exc
        return LLMImage(image.data, image.filename, image.content_type)

    def transcribe_audio(self, audio, filename, instructions, model=None):
        try:
            return self.client.transcribe_audio(audio, filename, instructions, model=model)
        except OpenAIAPIError as exc:
            raise LLMError(str(exc)) from exc
```

### 7.5 TeeBotusEngine minimal ändern

Nicht überall sofort umbenennen. Erst kompatibel:

```python
def __init__(
    self,
    ...,
    openai_client: object | None = None,
    llm_client: object | None = None,
    ...
) -> None:
    ...
    self.llm_client = llm_client if llm_client is not None else openai_client
    self.openai_client = self.llm_client  # Legacy-Alias
```

Danach in kleinen Commits:

```text
self.openai_client -> self.llm_client
_openai_actions bleibt vorerst als Name
später: _openai_actions -> _llm_actions mit Alias
```

### 7.6 Tests

Neue Tests:

```text
tests/test_llm_client.py
tests/test_llm_package.py
tests/test_openai_client.py
tests/test_engine_identity_flows.py
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_entrypoint_compatibility.py
python3 -m pytest -q tests/test_openai_client.py
python3 -m pytest -q tests/test_engine_identity_flows.py
python3 -m pytest -q tests/test_llm_client.py tests/test_llm_package.py
```

---

## 8. Phase 2 — LLM-Konfiguration neutralisieren

### 8.1 Neue BotInstructions-Felder

Bestehende `openai_*` Felder bleiben. Neue Felder kommen hinzu:

```python
llm_enabled: bool | None = None
llm_provider: str = ""
llm_model: str = ""
llm_api_key_env: str = ""
llm_base_url: str = ""
llm_timeout_seconds: int | None = None
llm_max_output_tokens: int | None = None
llm_temperature: float | None = None
llm_profile: str = ""
```

Regel:

```text
Wenn llm_enabled nicht None ist:
  neue LLM-Konfiguration hat Vorrang.

Wenn llm_enabled None ist:
  openai_enabled wird als Legacy verwendet.
```

### 8.2 Bot_Verhalten.md

Neu:

```markdown
## LLM
- enabled: true
- provider: litellm
- model: ollama_chat/llama3.1:8b
- base_url: http://127.0.0.1:11434
- timeout_seconds: 180
- max_output_tokens: 700
- temperature: 0.7
```

Legacy bleibt:

```markdown
## OpenAI
- enabled: true
- model: gpt-5.5
```

### 8.3 Env-Variablen

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT=litellm
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT=ollama_chat/llama3.1:8b
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT=http://127.0.0.1:11434
TEEBOTUS_LLM_API_KEY_DEPRESSIONSBOT=
```

Slot-spezifisch:

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT_TELEGRAM_1=litellm
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT_TELEGRAM_1=ollama_chat/llama3.1:8b
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT_TELEGRAM_1=http://127.0.0.1:11434
```

### 8.4 Auflösung

```text
1. TEEBOTUS_LLM_PROVIDER_<INSTANCE>_<CHANNEL>_<SLOT>
2. TEEBOTUS_LLM_PROVIDER_<INSTANCE>_<CHANNEL>
3. TEEBOTUS_LLM_PROVIDER_<INSTANCE>
4. TEEBOTUS_LLM_PROVIDER
5. Legacy OpenAI, wenn OPENAI_API_KEY vorhanden
6. none
```

### 8.5 RuntimeConfig erweitern

Bisherige Felder nicht entfernen. Ergänzen:

```python
llm_provider: str = ""
llm_model: str = ""
llm_api_key: str = ""
llm_base_url: str = ""
llm_profile: str = ""
```

`openai_api_key` bleibt Legacy.

### 8.6 Runtime-Status

```text
llm=Depressionsbot/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b base_url=127.0.0.1:11434 status=configured
llm=Depressionsbot/signal:1 provider=openai model=gpt-5.5 status=configured
llm=Depressionsbot/matrix:1 provider=none status=disabled
```

Keine Secrets anzeigen.

---

## 9. Phase 3 — LiteLLMProvider

### 9.1 litellm_provider.py

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    provider_name = "litellm"

    def __init__(self, settings: LiteLLMSettings) -> None:
        self.settings = settings

    def create_reply(self, user_text: str, instructions: object, previous_response_id: str | None = None) -> LLMResponse:
        try:
            from litellm import completion
        except Exception as exc:
            raise LLMError("LiteLLM ist nicht installiert. Installiere TeeBotus mit Extra [llm].") from exc

        system_text = ""
        if hasattr(instructions, "openai_instructions_text"):
            system_text = instructions.openai_instructions_text()

        messages: list[dict[str, str]] = []
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
            text=str(text).strip(),
            response_id=None,
            provider="litellm",
            model=self.settings.model,
            raw=None,
        )
```

### 9.2 Wichtig: previous_response_id

OpenAI Responses API kann `previous_response_id`. Providerneutrale Chat-Completions können das meist nicht.

Kurzfristig:

```text
- previous_response_id bei LiteLLM ignorieren.
- Memory, WorkingMemory, Bibliothekar und Weather-Kontext bleiben im Prompt.
```

Später:

```text
- eigene ConversationHistory pro Account/Instanz.
- History-Größe begrenzen.
- Sensitive Daten vermeiden.
```

### 9.3 Tests mit Fake

Nicht echte LiteLLM-Netzaufrufe im Unit-Test.

```python
def test_litellm_provider_maps_response(monkeypatch):
    ...
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_litellm_provider.py
python3 -m pytest -q
```

---

## 10. Phase 4 — Ollama lokal

### 10.1 Installation

Fedora/Generic:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Dienst prüfen:

```bash
systemctl status ollama || true
systemctl --user status ollama || true
curl http://127.0.0.1:11434/api/tags
```

### 10.2 Modelle

Start klein:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5:7b
```

Etwas stärker:

```bash
ollama pull qwen2.5:14b
ollama pull mistral-small
```

### 10.3 LiteLLM-Ollama Test

```python
from litellm import completion

response = completion(
    model="ollama_chat/llama3.1:8b",
    messages=[{"role": "user", "content": "Antworte auf Deutsch in einem Satz."}],
    api_base="http://127.0.0.1:11434",
)

print(response.choices[0].message.content)
```

### 10.4 TeeBotus .env

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT=litellm
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT=ollama_chat/llama3.1:8b
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT=http://127.0.0.1:11434
```

### 10.5 Bot_Verhalten.md

```markdown
## LLM
- enabled: true
- provider: litellm
- model: ollama_chat/llama3.1:8b
- base_url: http://127.0.0.1:11434
- timeout_seconds: 180
- max_output_tokens: 700
- temperature: 0.7
```

### 10.6 Akzeptanz

```bash
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m pytest -q
```

Manueller Bot-Test:

```text
- Bot privat anschreiben: "Sag in einem Satz, welcher Provider du bist."
- Log prüfen.
- Keine OpenAI-Abrechnung.
```

---

## 11. Phase 5 — Providerprofile für HuggingFace/Groq/Gemini

### 11.1 Profile-Datei

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

### 11.2 Routing-Datei

`config/llm_routing.yaml`:

```yaml
default_profile: local_ollama

purposes:
  normal_chat:
    profile: local_ollama
    fallback: null

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

  structured_decision:
    profile: local_ollama
    fallback: groq_fast
```

### 11.3 Keine versteckten Kosten

```text
- Remote-Fallback standardmäßig aus.
- Fallback pro Instanz explizit aktivieren.
- Jeder Provider-Fehler loggt Provider/Modell, aber keine Keys.
- Später Budget-Counter pro Instanz/Account.
```

---

## 12. Phase 6 — Haystack-Bibliothekar

### 12.1 Warum Haystack

Haystack passt, sobald der Bibliothekar viele Bücher/Dokumente bekommt:

```text
- Indexing-Pipelines
- Query-Pipelines
- Document Stores
- Retriever
- Reranker
- Metadata Filter
- Hybrid Search
- produktionsnähere RAG-Struktur
```

### 12.2 Trennung

```text
AccountStore / User-Memory:
- persönliche Erinnerungen
- Accountdaten
- Gewohnheiten
- Chat-bezogene Daten
- verschlüsselt
- NICHT in Haystack

Haystack Bibliothekar:
- Bücher
- PDFs
- EPUBs
- Markdown
- wissenschaftliche Quellen
- Regelwerke
- zitierfähige Dokumentstellen
```

### 12.3 Neue Ordnerstruktur

```text
TeeBotus/bibliothekar/
  __init__.py
  __main__.py
  cli.py
  config.py
  schema.py
  manifest.py
  converters.py
  chunking.py
  index_pipeline.py
  query_pipeline.py
  service.py
  citations.py

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

### 12.4 Dokument-Metadaten

Jeder Chunk braucht:

```yaml
source_id: sha256:<file_hash>
chunk_id: <source_id>:<page_start>:<chunk_index>
title: "Buchtitel"
author: "Autor"
file_path: "library/books/datei.pdf"
file_sha256: "..."
file_type: "pdf"
language: "de"
page_start: 12
page_end: 13
chapter: "Kapitel 2"
section: "Abschnitt 2.1"
license: "private"
ingested_at: "2026-06-15T12:00:00Z"
chunk_index: 42
embedding_model: "intfloat/multilingual-e5-small"
```

### 12.5 Chunking

```text
- 800–1200 Token pro Chunk
- 100–150 Token Overlap
- Kapitelgrenzen respektieren
- Seitenzahlen erhalten
- Tabellen markieren
- Überschriften in den Chunk-Kontext übernehmen
- Fußnoten nicht still entfernen
```

### 12.6 Qdrant lokal

```bash
podman volume create teebotus-qdrant

podman run -d \
  --name teebotus-qdrant \
  --restart=unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -v teebotus-qdrant:/qdrant/storage \
  qdrant/qdrant:latest
```

Produktiver:

```text
- kein latest im Dauerbetrieb
- Image-Tag pinnen
- Backup-Strategie für Volume
```

Healthcheck:

```bash
curl http://127.0.0.1:6333/collections
```

### 12.7 Embeddings

Start:

```text
intfloat/multilingual-e5-small
```

Besser, wenn Hardware reicht:

```text
intfloat/multilingual-e5-base
BAAI/bge-m3
```

Regeln:

```text
- Embedding-Modell im Manifest speichern.
- Bei Modellwechsel Index neu bauen.
- Für deutsche Bücher multilingual nutzen.
- Nicht denselben Chat-LLM als Embedding-Modell annehmen.
```

### 12.8 Bibliothekar CLI

```bash
python3 -m TeeBotus.bibliothekar status

python3 -m TeeBotus.bibliothekar index \
  --source library/inbox \
  --collection teebotus_books \
  --manifest data/bibliothekar/manifest.sqlite \
  --embedding-model intfloat/multilingual-e5-small

python3 -m TeeBotus.bibliothekar query \
  "Was steht in den Quellen zu ADHS und Arbeitsgedächtnis?" \
  --top-k 8
```

### 12.9 Index-Pipeline

```text
File Discovery
  -> Converter
  -> Cleaner
  -> Splitter
  -> Metadata Enricher
  -> Embedder
  -> DocumentStore Writer
  -> Manifest Update
```

### 12.10 Query-Pipeline

```text
Query
  -> Query Normalizer
  -> Metadata Filter
  -> Dense Retriever
  -> optional BM25 Retriever
  -> Joiner
  -> Reranker
  -> Top-K Chunks
  -> Citation Builder
  -> LLM-Kontext
```

### 12.11 Antwortregeln

```text
Wenn Bibliothekar-Modus aktiv ist:
- Keine zentrale Behauptung ohne Quelle.
- Quellen mit Titel, Kapitel/Seite, Chunk-ID.
- Kurze Zitate, keine langen Buchpassagen.
- Wenn nichts gefunden: ehrlich sagen.
- Keine User-Memorys in Quellenkontext mischen.
```

### 12.12 Integration in TeeBotusEngine

Bestehende Bibliothekar-Kontextfunktion wird ersetzt/erweitert:

```text
_build_bibliothekar_context(...)
  -> BibliothekarService.search(query, filters, top_k)
  -> formatierte Chunks + Quellen
  -> Prompt-Kontext
```

Neue Bot-Verhalten-Sektion:

```markdown
## Bibliothekar
- enabled: true
- backend: haystack
- collection: teebotus_books
- max_chunks: 5
- max_prompt_chars: 5000
- max_quote_chars: 900
- require_citations: true
```

### 12.13 Akzeptanz

```bash
python3 -m TeeBotus.bibliothekar index --source tests/fixtures/books --dry-run
python3 -m TeeBotus.bibliothekar query "Testfrage" --top-k 3
python3 -m pytest -q tests/test_bibliothekar_*.py
```

---

## 13. Phase 7 — Pydantic AI für strukturierte Entscheidungen

### 13.1 Einsatzgebiete

```text
Geeignet:
- Intent-Erkennung
- Memory-Kandidaten
- Reminder-Erkennung
- YouTube-Optionsparser
- Tool-Plan-Validierung
- Bibliothekar-Frageklassifikation

Nicht geeignet:
- /ping
- /help
- /status
- feste Slash-Kommandos
- Kern-Runtime ersetzen
```

### 13.2 Schemas

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
    memory_type: Literal[
        "preference",
        "profile",
        "habit",
        "project",
        "relationship",
        "none",
    ]
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

### 13.3 Regeln

```text
- Slash-Commands zuerst klassisch parsen.
- Pydantic AI nur bei natürlicher Sprache.
- confidence < 0.70 -> nicht automatisch handeln.
- sensitivity high -> nicht automatisch speichern.
- echte Tool-Aktionen brauchen zusätzlich Policy.
```

### 13.4 Tests

```bash
python3 -m pytest -q tests/test_pydantic_decisions.py
```

---

## 14. Phase 8 — LangGraph sinnvoll einsetzen

LangGraph ist nicht Ersatz für TeeBotusEngine. LangGraph ist die Workflow-Maschine.

### 14.1 Gute Kandidaten

```text
Proactive-Agent:
  observe -> plan -> select_due -> generate -> safety -> dispatch -> record

Bibliothekar Deep Query:
  classify -> retrieve -> rerank -> answer -> citation_check -> fallback

Codex Task:
  authorize -> plan -> sandbox -> execute -> summarize -> approval

YouTube:
  detect -> fetch captions -> local transcribe -> summarize -> memory decision

Account-Linking Security:
  login -> notify old identities -> grace period -> WTF rollback -> rotate secret
```

### 14.2 Schlechte Kandidaten

```text
- /ping
- /help
- /status
- einfache Textantworten
- normaler Chat ohne Spezialworkflow
```

### 14.3 Struktur

```text
TeeBotus/runtime/graphs/
  __init__.py
  proactive_graph.py
  bibliothekar_graph.py
  codex_graph.py
```

LangGraph optional laden:

```python
try:
    import langgraph
except ImportError:
    langgraph = None
```

Akzeptanz:

```text
- Bot läuft ohne installiertes LangGraph.
- Graph-Flows laufen, wenn Extra [agents] installiert ist.
- State ist serialisierbar.
- Fehler produzieren keine halben Memory-Schreibungen.
```

---

## 15. Phase 9 — MCP/FastMCP später

Nicht jetzt als erstes einbauen. Erst Provider/RAG stabilisieren.

### 15.1 Erste erlaubte Tools

```yaml
mcp_tools:
  bibliothekar.search:
    enabled: true
    read_only: true

  memory.search:
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

### 15.2 Verboten

```text
- freie Shell
- Schreibzugriff auf .env
- Lesen von beliebigen Pfaden
- Secret-Ausgabe
- ungeprüftes Löschen
- Netzwerk-/Portscans
- Toolzugriff in Gruppen ohne harte Regeln
```

---

## 16. Runtime-Status Zielausgabe

```text
TeeBotus runtime configuration resolves.
instances_dir=instances
instances=Depressionsbot
channels=telegram,signal,matrix

llm=Depressionsbot/telegram:1 provider=litellm model=ollama_chat/llama3.1:8b base_url=127.0.0.1:11434 status=configured
ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b,qwen2.5:7b

bibliothekar=Depressionsbot backend=haystack store=qdrant collection=teebotus_books status=reachable documents=12421 chunks=98334

signal_service=Depressionsbot/signal:1 target=127.0.0.1:8080 status=reachable
matrix_homeserver=Depressionsbot/matrix:1 target=matrix.example:443 status=reachable
```

Tests:

```text
tests/test_runtime_status_llm.py
tests/test_runtime_status_bibliothekar.py
```

---

## 17. Telegram als additiver Runtime-Slot

Der alte Satz "Telegram läuft weiter über den vorhandenen Poller" war zu konservativ. Er beschreibt eine Transportimplementierung, aber keine gute Zielarchitektur.

Ziel:

```text
Telegram ist wie Signal und Matrix ein additiver Runtime-Slot.
Der Telegram-Poller bleibt vorerst nur der konkrete Receive-Transport.
Der Bot-Kern darf nicht mehr um den Telegram-Poller herum organisiert sein.
```

### 17.1 Warum nicht sofort Polling löschen

```text
- Telegram braucht weiterhin einen Receive-Mechanismus: Long-Polling oder Webhook.
- TeeBotus.adapters.telegram_runtime enthaelt noch viel Telegram-spezifische Produktlogik:
  Attachments, Voice, YouTube-Live-Ausgabe, Message-Tracking, Cleanup,
  Linked-Identity-Notifications, Status, TTS-Kommandos.
- Proactive/Telegram nutzt noch direkt TelegramAPI.
- Viele Tests pruefen aktuell run_polling und Telegram-kompatibles Verhalten.
```

Darum:

```text
Nicht:
  Telegram-Poller sofort loeschen.

Sondern:
  TelegramRuntimeSlot / TelegramRuntimeBridge einfuehren.
  run_polling intern als Transport behalten.
  Telegram ueber dieselbe Runtime-Orchestrierung starten wie Signal/Matrix.
```

### 17.2 Zielstruktur

```text
TeeBotus.runtime.telegram_runner
  ├─ TelegramRuntimeBridge
  ├─ start_telegram_accounts(...)
  ├─ start_telegram_accounts_in_background(...)
  └─ Telegram transport:
       ├─ polling
       └─ spaeter optional webhook

TeeBotus.adapters.telegram_runtime
  ├─ TelegramAPI
  ├─ Telegram-spezifische Event-Konvertierung
  ├─ Telegram-spezifisches Action-Sending
  └─ Polling-Transport als Kompatibilitaetslayer
```

### 17.3 Migrationsschritte

```text
1. TelegramRuntimeBridge analog zu MatrixRuntimeBridge/TeeBotusSignalCommand bauen.
2. Engine-/Store-/LLM-/Bibliothekar-Aufbau aus telegram_runtime.run_polling herausziehen.
3. bot.py startet Telegram ueber runtime.telegram_runner, nicht direkt ueber Telegram-Main.
4. run_polling bleibt als interner Transport und Kompatibilitaetsfunktion erhalten.
5. Runtime-Status meldet Telegram-Slots wie Signal/Matrix-Slots.
6. Tests von "Telegram ist Entry-Point" auf "Telegram ist Runtime-Slot" umstellen.
7. Optional spaeter Telegram-Webhook als zweiter Transport.
```

### 17.4 Akzeptanz

```bash
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix
python3 -m pytest -q tests/test_bot.py tests/test_runtime_config.py tests/test_adapters.py
```

Akzeptanzkriterien:

```text
- python3 -m TeeBotus bleibt stabil.
- python3 -m TeeBotus --all bleibt stabil.
- Telegram startet als Slot ueber die gemeinsame Runtime-Orchestrierung.
- Telegram-Long-Polling funktioniert weiter.
- Telegram-Transport ist austauschbar genug fuer spaeteres Webhook-Backend.
- Signal/Matrix bleiben unveraendert additive Slots.
```

---

## 18. systemd

### 18.1 Qdrant als User-Service

```bash
podman generate systemd --new --files --name teebotus-qdrant
mkdir -p ~/.config/systemd/user
mv container-teebotus-qdrant.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now container-teebotus-qdrant.service
```

### 18.2 TeeBotus Service

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

Aktivieren:

```bash
systemctl --user daemon-reload
systemctl --user enable --now teebotus.service
journalctl --user -u teebotus.service -f
```

---

## 19. CI-Plan

`.github/workflows/tests.yml`:

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  test-core:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv venv --python 3.12
      - run: uv pip install -e ".[dev]"
      - run: uv run pytest -q

  test-llm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv venv --python 3.12
      - run: uv pip install -e ".[dev,llm]"
      - run: uv run pytest -q tests/test_llm_client.py tests/test_litellm_provider.py tests/test_llm_package.py tests/test_openai_client.py

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv venv --python 3.12
      - run: uv pip install -e ".[dev,llm]"
      - run: uv run pip-audit
```

---

## 20. Rollback

### 20.1 Schnell-Rollback auf OpenAI

`.env`:

```bash
TEEBOTUS_LLM_PROVIDER_DEPRESSIONSBOT=openai
TEEBOTUS_LLM_MODEL_DEPRESSIONSBOT=
TEEBOTUS_LLM_BASE_URL_DEPRESSIONSBOT=
OPENAI_API_KEY_DEPRESSIONSBOT=sk-...
```

### 20.2 LLM abschalten

```bash
TEEBOTUS_LLM_ENABLED_DEPRESSIONSBOT=false
```

### 20.3 Git-Rollback

```bash
git checkout main
python3 -m TeeBotus --runtime-status --channels telegram
```

### 20.4 Daten-Rollback

```bash
systemctl --user stop teebotus.service || true

tar -xzf backups/<timestamp>/instances-data.tgz -C .
cp backups/<timestamp>/.env.backup .env

systemctl --user start teebotus.service || true
```

Haystack/Qdrant Index ist rebuildbar. Kritisch sind nur:

```text
- AccountStore
- verschlüsselte Memory-Dateien
- .env
- Instance-Konfiguration
```

---

## 21. Codex-Aufträge

### Auftrag 1 — LLM-Interface

```text
Erstelle TeeBotus/llm/base.py, capabilities.py, openai_provider.py.
Baue OpenAIClient als Provider-Wrapper ein.
Aendere TeeBotusEngine minimal auf llm_client mit openai_client Legacy-Alias.
Entferne keine OpenAI-Funktion.
Alle bestehenden Tests müssen grün bleiben.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_entrypoint_compatibility.py tests/test_openai_client.py
python3 -m TeeBotus --version
```

### Auftrag 2 — neutrale Config

```text
Ergänze llm_* Felder in BotInstructions.
openai_* bleibt Legacy.
Ergänze RuntimeConfig um llm_provider, llm_model, llm_api_key, llm_base_url.
Implementiere Env-Auflösung mit TEEBOTUS_LLM_* und OpenAI-Fallback.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_runtime_config.py tests/test_llm_config.py
```

### Auftrag 3 — LiteLLMProvider

```text
Implementiere LiteLLMTextClient.
Nutze keine echten Provider in Unit-Tests.
Constraints müssen litellm!=1.82.7,!=1.82.8 enthalten.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_litellm_provider.py
pip-audit || true
```

### Auftrag 4 — Ollama-Profil

```text
Dokumentiere Ollama-Konfiguration.
Erweitere Runtime-Status.
Baue optionalen lokalen Healthcheck für 127.0.0.1:11434.
```

Akzeptanz:

```bash
python3 -m TeeBotus --runtime-status --channels telegram
```

### Auftrag 5 — Providerprofile

```text
Baue config/llm_profiles.yaml und config/llm_routing.yaml.
Implementiere Router-Auswahl nach purpose.
Remote-Fallback standardmäßig deaktivieren.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_llm_router.py
```

### Auftrag 6 — Haystack-Bibliothekar Grundgerüst

```text
Erstelle TeeBotus/bibliothekar Paket.
Implementiere Schema, Manifest, Chunking, Citation Builder.
Starte mit Markdown/TXT Fixtures.
```

Akzeptanz:

```bash
python3 -m TeeBotus.bibliothekar index --source tests/fixtures/books --dry-run
python3 -m TeeBotus.bibliothekar query "Testfrage" --top-k 3
python3 -m pytest -q tests/test_bibliothekar_*.py
```

### Auftrag 7 — Qdrant/Haystack produktiv

```text
QdrantDocumentStore anbinden.
Indexing Pipeline bauen.
Query Pipeline bauen.
Runtime-Status für Bibliothekar ergänzen.
```

Akzeptanz:

```bash
curl http://127.0.0.1:6333/collections
python3 -m TeeBotus.bibliothekar status
```

### Auftrag 8 — Pydantic AI

```text
IntentDecision, MemoryCandidate, ReminderDecision implementieren.
Nur bei natürlicher Sprache aktivieren.
Slash-Commands bleiben klassische Parser.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_pydantic_decisions.py
```

### Auftrag 9 — LangGraph Pilot

```text
Erstelle TeeBotus/runtime/graphs.
Migriere genau einen Flow als Pilot: Bibliothekar Deep Query oder Proactive-Agent.
Normale Chatantworten dürfen ohne LangGraph laufen.
```

Akzeptanz:

```bash
python3 -m pytest -q tests/test_graphs_*.py
```

### Auftrag 10 — Telegram Runtime-Slot

```text
Loese Telegram als Architektur-Sonderfall auf.
Baue Telegram als additiven Runtime-Slot analog Signal/Matrix.
Kapsle den vorhandenen Long-Poller als Telegram-Transport.
Loesche den Poller nicht in diesem Schritt.
```

Akzeptanz:

```bash
python3 -m TeeBotus --runtime-status --channels telegram
python3 -m TeeBotus --runtime-status --channels telegram,signal,matrix
python3 -m pytest -q tests/test_bot.py tests/test_entrypoint_compatibility.py tests/test_adapters.py
```

### Auftrag 11 — Dokumentation

```text
README aktualisieren:
- LLM-Router
- Ollama Quickstart
- HF/Groq/Gemini Profile
- Haystack-Bibliothekar
- Security / LiteLLM Supply-Chain Hinweis
- Rollback
- Datenschutz DE/EN
```

Akzeptanz:

```text
README enthält keine Secrets.
README erklärt, dass Account-Memory nicht in Haystack liegt.
README erklärt lokale vs. Remote-Provider.
```

---

## 22. Reihenfolge

```text
Tag 1:
- Branch, Baseline, pyproject, dev tests

Tag 2:
- LLM-Interface + OpenAIProvider Wrapper

Tag 3:
- llm_* Config + Runtime-Status

Tag 4:
- LiteLLMProvider + Tests

Tag 5:
- Ollama lokal + Bot-Test

Tag 6:
- Providerprofile HF/Groq/Gemini

Tag 7:
- Haystack Bibliothekar Skeleton

Tag 8:
- Qdrant + Markdown/TXT Indexing

Tag 9:
- PDF/EPUB Ingestion + Citation Builder

Tag 10:
- Pydantic AI Subtasks

Tag 11+:
- LangGraph Pilot
- MCP/FastMCP read-only Pilot
- Telegram Runtime-Slot Migration
```

---

## 23. Definition of Done

```text
- python3 -m TeeBotus funktioniert.
- python3 -m TeeBotus --all funktioniert.
- Telegram startet als additiver Runtime-Slot.
- Telegram-Long-Polling funktioniert als Transport weiter.
- Telegram/Signal/Matrix Runtime-Status bleibt intakt.
- OpenAI Legacy funktioniert.
- Ollama funktioniert als Text-Provider.
- HuggingFace/Groq/Gemini sind als Profile vorbereitet.
- Haystack kann Testbücher indexieren und mit Quellen abfragen.
- Account-Memory bleibt getrennt und verschlüsselt.
- Keine Secrets im Repo.
- Tests für Entry-Point, RuntimeConfig, LLMRouter, LiteLLM, Bibliothekar und Pydantic-Subtasks existieren.
- Rollback ist dokumentiert.
```

---

## 24. Quellen und Dokumentation

- LiteLLM: https://docs.litellm.ai/
- LiteLLM Ollama: https://docs.litellm.ai/docs/providers/ollama
- LiteLLM Hugging Face: https://docs.litellm.ai/docs/providers/huggingface
- Haystack Pipelines: https://docs.haystack.deepset.ai/docs/pipelines
- Haystack Document Store: https://docs.haystack.deepset.ai/docs/document-store
- Pydantic AI Models: https://pydantic.dev/docs/ai/models/overview/
- LangGraph Overview: https://docs.langchain.com/oss/python/langgraph/overview
- signal-cli: https://github.com/AsamK/signal-cli



## 25. Repo-Abgleich 2026-06-19

Plan v2 bleibt der Hauptarbeitsplan, aber der Repo-Stand ist weiter als der
urspruengliche Download-Text. Dieser Abschnitt ersetzt den alten Nachtrag und
haelt die aktuellen Leitplanken fest.

Aktueller `pyproject.toml`-Vertrag:

```toml
[project]
name = "teebotus"
dynamic = ["version"]
requires-python = ">=3.11"

[project.optional-dependencies]
dev = ["pytest==9.1.1", "pytest-cov", "ruff", "mypy", "pip-audit"]
llm = ["litellm==1.89.2", "openai==2.43.0; python_version < '3.14'", "openai==2.30.0; python_version >= '3.14'", "ollama==0.6.2"]
rag = ["haystack-ai==2.30.2", "qdrant-haystack==10.3.0", "sentence-transformers==5.6.0", "pypdf==6.13.3", "pymupdf==1.27.2.3", "ebooklib==0.20", "beautifulsoup4==4.15.0", "llama-index-core==0.14.22"]
agents = ["pydantic-ai-slim==1.107.0", "langgraph==1.2.6"]
tools = ["fastmcp==3.4.2", "python-dotenv==1.2.2", "watchdog==6.0.0"]
```

Aktueller Architekturstand:

- Der Entry-Point bleibt gesund: `TeeBotus/__main__.py` delegiert an `TeeBotus.bot.main`; `TeeBotus.bot` bleibt die Kompatibilitaetsbruecke.
- Telegram, Signal und Matrix werden als additive Runtime-Slots behandelt; Telegram-Long-Polling ist Transport, nicht Kernarchitektur.
- Die neutrale Text-LLM-Schicht existiert: `TeeBotus/llm/base.py`, `TeeBotus/llm/openai_provider.py`, `TeeBotus/llm/litellm_provider.py`, Profile unter `config/` und Runtime-Routing.
- `llm_provider`, `llm_model`, `llm_base_url`, `llm_api_key` und Purpose-Routing sind die neutralen Text-LLM-Konfigurationsachsen.
- `OpenAIClient` bleibt Spezialclient fuer Responses, Websuche, Tool Calls, Speech, Bilder und Transkription; er wird nicht geloescht.
- `missing_key`, `error` und `reset` im `## LLM`-Block sind die neutralen Texte fuer Text-LLM-Antworten und Reset. OpenAI-spezifische Spezialfunktionen wie Voice, Bilder und OpenAI-Transkription behalten eigene `openai_*`-/`voice_*`-/`image_*`-/`transcription_*`-Texte.
- Der Bibliothekar ist kein Neubau mehr: bestehende lokale Store-/Service-Strukturen bleiben die Kompatibilitaetsbasis; Haystack/Qdrant werden als optionale Backends angebunden.

Aktuelle Prioritaeten:

1. LLM-Router und Profile haerten, nicht ersetzen.
2. Lokale und Remote-Provider ueber Tests, Runtime-Status und Benchmarks verifizieren.
3. Bibliothekar-Backend-Abstraktion pflegen und Haystack/Qdrant dahinter setzen.
4. Pydantic AI fuer strukturierte Entscheidungen einsetzen.
5. LangGraph nur fuer lange, kontrollierte Workflows nutzen.
6. MCP/FastMCP nur allowlisted und read-only zuerst freigeben.

Merksatz: TeeBotus wird nicht um ein Framework herum neu gebaut; Frameworks und Provider werden als austauschbare Module in TeeBotus eingebaut.

---

## Zusatzauftrag — Valide Benchmarktests fuer alles

Baue valide, reproduzierbare Benchmarktests fuer alle relevanten TeeBotus-Kernpfade.

Abdecken:

- Account-Memory: JSON/SQL/PostgreSQL-Pfade, Lesen, Schreiben, Suche, Index-Rebuild, Migration.
- Bibliothekar: lokaler Store, Haystack/Qdrant-Backend, Indexing, Query, Citation-Payload-Aufbau.
- LLM-Router: Provider-Auswahl, Fallback-Entscheidung, strukturierte Decisions ohne echte Provider-Calls.
- Proactive-Agent: Planen, Due-Selection, Dispatch-Simulation, Safety-/Policy-Gates.
- Messenger-Adapter: Telegram, Signal, Matrix Runtime-Checks ohne echte Netzsendung.
- Transkription/YouTube: lokale Pipeline, Parser, Job-Queue, keine OpenAI-Fallbackkosten.
- Status/Doctor: Laufzeitstatus, Dependency-Checks, Backend-Health.
- Datenbank-Fallback: Primär-/Sekundärdatenbank, Sync, Fallback-Warnlogik.
- LangGraph-Flows: Pilotgraphen linear und mit installiertem LangGraph.

Benchmarkregeln:

- Keine echten API-Kosten in Standard-Benchmarks.
- Netzwerk/Provider in den Messungen nur hinter explizitem Override; der Quick-CLI-Lauf darf den fertigen Bericht danach an Admin-Accounts senden.
- Fixtures muessen klein, versioniert und reproduzierbar sein.
- Ausgabe als Markdown und JSON standardmaessig nach `/home/teladi/Dokumente/Obsidian_Vaults/Teladi_Programming/incomming`.
- `python3 scripts/run_benchmarks.py --quick` verschickt den Markdown-Bericht zusaetzlich messenger-agnostisch an die Admin-Accounts; trockene Laeufe nutzen `--no-admin-notify` und bei Bedarf `--no-obsidian`.
- Jeder Benchmark nennt Hardware-/Python-/Dependency-Kontext.
- Jeder Benchmark misst mindestens Laufzeit, Durchsatz, Fehlerzahl und relevante Payload-/Indexgroessen.
- Benchmarks duerfen nicht nur Smoke-Tests sein; sie muessen Vergleichswerte liefern.
- Benchmarks muessen in CI/Local-Modus mit Fake-Backends laufen und optional Live-Backends vergleichen.

Akzeptanz:

```bash
python3 -m pytest -q tests/test_benchmarks_*.py
python3 scripts/run_benchmarks.py --quick
```

Definition of Done:

- Fuer jeden Kernpfad gibt es mindestens einen validen Benchmark.
- Benchmarks sind deterministisch genug, um Regressionen sichtbar zu machen.
- Langsame/live Benchmarks sind klar markiert und standardmaessig aus.
- Die schnellsten stabilen Backends werden dokumentiert, aber nicht blind automatisch umgeschaltet.

Baue valide Benchmarktests fuer alles.
