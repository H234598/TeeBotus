# Memory Schema V2

TeeBotus account memory uses `User_Memory_Entries.jsonl` as the source of truth. `User_Memory_Index.json` is a rebuildable index for fast retrieval, graph traversal, health checks, and optional semantic cache data.

## Entry Store

The JSONL entry store has no default total-entry limit. Runtime selection is still budgeted by prompt size, index windows, and cache size so the bot remains usable on a modern notebook CPU.

Core V2 fields:

- `schema_version`: `2`
- `kind`: typed memory category
- `importance`: stable user/domain importance, `1..5`
- `salience`: retrieval urgency, `1..10`
- `decay`: retention/compaction policy metadata
- `keywords`: lexical lookup terms
- `related_ids`, `supports`, `contradicts`, `supersedes`: typed graph links to other memory IDs
- `source`: channel/message provenance
- `user_text`, `bot_text`: compact episodic payload

## Kinds

General kinds include `observation`, `episode`, `self_statement`, `preference`, `fact`, `biographical_fact`, `task`, `manual`, `reflection`, `summary`, `correction`, `boundary`, `consent`, and `procedural`.

Depressionsbot and psychoanalytic work can additionally use `clinical_signal`, `risk_signal`, `protective_factor`, `trigger`, `coping_strategy`, `relationship_pattern`, `attachment_pattern`, `cognitive_pattern`, `affect_pattern`, `defense_pattern`, `therapy_goal`, `intervention_response`, `hypothesis`, `psychoanalytic_hypothesis`, `semantic_contradiction`, `compaction`, and `decay_marker`.

Clinical and psychoanalytic kinds are signals or hypotheses, not diagnoses. They should keep provenance through `source` and graph links.

## Index

The V2 index contains:

- `index.entries`: compact metadata per memory ID
- `index.keywords`: bounded keyword-to-ID lookup
- `index.recent_ids`: bounded recent lookup window
- `index.graph.links`: typed link maps for `related_ids`, `supports`, `contradicts`, and `supersedes`
- `index.semantic_cache`: optional rebuildable cache generated from JSONL
- `index.retention`: local policy metadata

The semantic cache currently uses keyword signatures and fingerprints. It is intentionally rebuildable from JSONL and can later be replaced or extended with embeddings without changing the source-of-truth entry format.
