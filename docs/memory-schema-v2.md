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
- `index.graph.links`: typed link maps for `related_ids`, `supports`, `contradicts`, and `supersedes`
- `index.semantic_cache`: optional rebuildable cache generated from JSONL
- `index.retention`: local policy metadata

The semantic cache currently uses keyword signatures and fingerprints. It is intentionally rebuildable from JSONL and can later be replaced or extended with embeddings without changing the source-of-truth entry format.
