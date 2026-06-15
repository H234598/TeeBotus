# Memory Schema V2

TeeBotus account memory uses `User_Memory_Entries.jsonl` as the source of truth. `User_Memory_Index.json` is a rebuildable index for fast retrieval, graph traversal, health checks, and optional semantic cache data.

## Entry Store

The JSONL entry store has no default total-entry limit. Runtime selection is still budgeted by prompt size, index windows, and cache size so the bot remains usable on a modern notebook CPU.

Core V2 fields:

- `schema_version`: `2`
- `kind`: typed memory category
- `memory_type`: `episodic`, `semantic`, or `procedural`
- `importance`: stable user/domain importance, `1..5`
- `salience`: retrieval urgency, `1..10`
- `decay`: retention/compaction policy metadata
- `last_accessed_at`, `access_count`: real recall metadata, separate from write recency
- `valid_from`, `valid_to`: optional temporal validity for facts/hypotheses
- `keywords`: lexical lookup terms
- `related_ids`, `supports`, `contradicts`, `supersedes`: typed graph links to other memory IDs
- `relations`: typed temporal relation edges with `target_id`, `valid_from`, `valid_to`, `provenance`, and optional `confidence`
- `source`: channel/message provenance
- `user_text`, `bot_text`: compact episodic payload

## Kinds

General kinds include `observation`, `episode`, `self_statement`, `preference`, `fact`, `biographical_fact`, `task`, `manual`, `reflection`, `summary`, `correction`, `boundary`, `consent`, and `procedural`.

Depressionsbot and psychoanalytic work can additionally use `clinical_signal`, `risk_signal`, `protective_factor`, `trigger`, `coping_strategy`, `relationship_pattern`, `attachment_pattern`, `cognitive_pattern`, `affect_pattern`, `defense_pattern`, `therapy_goal`, `intervention_response`, `hypothesis`, `psychoanalytic_hypothesis`, `semantic_contradiction`, `compaction`, and `decay_marker`.

Psychiatric and psychotherapy note-derived kinds:

- Progress note sections: `subjective_note`, `objective_note`, `assessment_note`, `plan_note`, `data_note`, `behavior_note`, `intervention_note`, `response_note`, `problem_note`, `goal_note`, `session_objective`
- Intake and history: `chief_complaint`, `presenting_problem`, `history_present_illness`, `psychiatric_history`, `medical_history`, `family_history`, `developmental_history`, `substance_use_history`, `trauma_history`, `social_history`, `cultural_context`, `legal_context`
- Functioning: `occupational_functioning`, `school_functioning`, `functional_impairment`
- Biopsychosocial and formulation factors: `biological_factor`, `psychological_factor`, `social_factor`, `presenting_factor`, `predisposing_factor`, `precipitating_factor`, `perpetuating_factor`
- Mental status exam: `mse_appearance`, `mse_behavior`, `mse_speech`, `mse_mood`, `mse_affect`, `mse_thought_process`, `mse_thought_content`, `mse_perception`, `mse_cognition`, `mse_orientation`, `mse_attention`, `mse_memory`, `mse_insight`, `mse_judgment`, `mse_impulse_control`
- Symptom and body-state signals: `sleep_pattern`, `appetite_pattern`, `energy_pattern`, `somatic_symptom`, `panic_symptom`, `anxiety_signal`, `mood_signal`, `psychosis_signal`, `dissociation_signal`, `obsession_compulsion_signal`
- Risk and safety: `suicidal_ideation`, `self_harm_signal`, `violence_risk_signal`, `neglect_risk_signal`, `means_access`, `risk_assessment`, `safety_plan`, `crisis_plan`, `action_taken`
- Diagnostic and formulation caution: `diagnostic_hypothesis`, `differential_diagnosis`, `diagnostic_uncertainty`, `case_formulation`
- Therapy process: `treatment_goal`, `treatment_plan`, `homework`, `skill_practice`, `therapeutic_alliance`, `rupture_repair`, `transference_pattern`, `countertransference_note`, `resistance_pattern`, `dream_material`, `free_association_theme`, `psychotherapy_process_note`
- Medication and treatment response: `medication`, `medication_adherence`, `side_effect`, `medication_response`, `substance_craving`, `screening_result`, `measurement_score`
- Care operations: `care_coordination`, `collateral_information`, `next_step`, `follow_up`, `discharge_plan`

Clinical and psychoanalytic kinds are signals or hypotheses, not diagnoses. They should keep provenance through `source` and graph links.

## Index

The V2 index contains:

- `index.entries`: compact metadata per memory ID
- `index.keywords`: bounded keyword-to-ID lookup
- `index.recent_ids`: bounded recent lookup window
- `index.accessed_ids`: bounded real recall-recency window
- `index.types`: memory IDs split into `episodic`, `semantic`, and `procedural`
- `index.graph.links`: typed link maps for `related_ids`, `supports`, `contradicts`, and `supersedes`
- `index.graph.relations`: typed temporal relation edges, rebuildable from entries
- `index.semantic_cache`: optional rebuildable cache generated from JSONL
- `index.retention`: local policy metadata

The semantic cache currently uses local hash embeddings plus keyword signatures and fingerprints. It is intentionally rebuildable from JSONL and can later be replaced or extended with model embeddings without changing the source-of-truth entry format. Operators can disable it by setting `index.semantic_cache.enabled` to `false`; rebuild then keeps the cache empty and keyword/recent retrieval still works.

## Architecture Comparison

- Generative Agents: TeeBotus keeps the memory-stream idea and ranks by relevance, recency, and importance. Reflection is represented by `summary`/`reflection` entries created by maintenance jobs. TeeBotus is not a full autonomous simulation/planning agent.
- MemGPT/Letta: TeeBotus has fast prompt hydration plus slower encrypted JSONL archive. It now supports one bounded active paging round per user turn: the model can request a further local account-memory page, TeeBotus retrieves it from JSONL/index data, and then asks the model for the final answer.
- LangGraph/LangChain Memory: TeeBotus separates account long-term memory from instance working memory and now distinguishes `semantic`, `episodic`, and `procedural` account entries.
- Mem0: TeeBotus performs local deterministic consolidation from repeated episodes into semantic summaries with provenance. It avoids a mandatory LLM/vector-service dependency.
- Zep/Graphiti: TeeBotus now has a small local temporal graph with typed relations, validity windows, provenance, and conflict links. It is intentionally not a separate graph database.

## Active Paging

Normal prompt hydration selects a bounded first page from account memory. If that page is not enough, the model may answer exactly:

```text
[[TEE_MEMORY_PAGE query="short search phrase" exclude="mem_id_1,mem_id_2"]]
```

TeeBotus then loads one additional page locally with `exclude_ids` applied, updates `last_accessed_at`/`access_count` for the loaded memories, and performs one second OpenAI call with the page and the original user message. The hard one-page limit prevents model loops and keeps latency predictable on a notebook CPU. This is a local protocol today; a native OpenAI function-tool wrapper can later call the same `select_structured_memory(..., exclude_ids=...)` path.

## Graph Server

A graph server would mainly add durable graph queries, multi-hop traversal, consistency constraints, concurrent writes, graph algorithms, and external visualization over the same relation data. It is useful once the local JSONL/index graph becomes too large, needs multi-process access, or needs query patterns such as "find all active contradictions involving this risk hypothesis across several relation hops".

For the current TeeBotus target, JSONL remains the source of truth and `index.graph` is a rebuildable local cache. That keeps privacy, portability, encryption, backups, and notebook-CPU operation simpler. A future graph server should therefore be an optional rebuildable projection, not the primary memory store.

## Maintenance

`AccountStore.run_memory_maintenance(account_id)` is the notebook-friendly background job entrypoint. It rebuilds the index and consolidates repeated episodic themes into semantic summaries with `derived_from` relations. The hot path still writes the original episode first; heavier consolidation can run later.
