# Changelog

## 1.9.126 - 2026-07-12

- Normalize umlaut-bearing historical and habitual loudness markers.

## 1.9.125 - 2026-07-12

- Reject non-private routes in notification-loudness outbox items.

## 1.9.124 - 2026-07-12

- Restrict loudness route refresh to account-owned identities.

## 1.9.123 - 2026-07-12

- Ignore inverted loudness questions without question marks.

## 1.9.122 - 2026-07-12

- Avoid treating no-longer notification states as current.

## 1.9.121 - 2026-07-12

- Ignore habitual notification-loudness statements as current state.

## 1.9.120 - 2026-07-12

- Ignore negated keep/leave requests as completed loudness states.

## 1.9.119 - 2026-07-12

- Ignore conditional notification-loudness statements.

## 1.9.118 - 2026-07-12

- Avoid treating historical notification status as current.

## 1.9.117 - 2026-07-12

- Distinguish present notification actions from completed states.

## 1.9.116 - 2026-07-12

- Ignore future notification-loudness intentions as completed states.

## 1.9.115 - 2026-07-12

- Ignore notification-loudness requests as completed states.

## 1.9.114 - 2026-07-12

- Recognize explicit English uncertainty markers in loudness replies.

## 1.9.113 - 2026-07-12

- Recognize contracted uncertainty in loudness status replies.

## 1.9.112 - 2026-07-12

- Recheck loudness account ownership inside state locks.

## 1.9.111 - 2026-07-12

- Recognize affirmation variants with explicit notification context.

## 1.9.110 - 2026-07-12

- Reject negated positive notification status substrings.

## 1.9.109 - 2026-07-12

- Prioritize explicit negated mute status over generic English refusals.

## 1.9.108 - 2026-07-12

- Handle contracted English negations in loudness replies.

## 1.9.107 - 2026-07-12

- Recognize completion synonyms in loudness replies.

## 1.9.106 - 2026-07-12

- Recognize message and push context in loudness status replies.

## 1.9.105 - 2026-07-12

- Recognize concise pending loudness action replies.

## 1.9.104 - 2026-07-12

- Enforce account ownership for notification-loudness events.

## 1.9.103 - 2026-07-12

- Respect negated loudness completion phrases.

## 1.9.102 - 2026-07-12

- Distinguish status fragments from inverted loudness questions.

## 1.9.101 - 2026-07-12

- Ignore notification-loudness questions and requests as confirmations.

## 1.9.100 - 2026-07-12

- Do not treat loudness imperatives as completed confirmations.

## 1.9.99 - 2026-07-12

- Avoid deciding notification loudness from uncertain status statements.

## 1.9.98 - 2026-07-12

- Preserve punctuation clause boundaries in loudness negation parsing.

## 1.9.97 - 2026-07-12

- Prevent notification-loudness negation leakage across clauses.

## 1.9.96 - 2026-07-12

- Fix notification-loudness negation precedence for compound status phrases.

## 1.9.95 - 2026-07-12

- Preserve negation when parsing disabled notification statuses.

## 1.9.94 - 2026-07-12

- Recognize English notification status and mute replies.

## 1.9.93 - 2026-07-12

- Recognize natural on/off and loud notification status replies.

## 1.9.92 - 2026-07-12

- Distinguish negated mute phrases in notification-loudness replies.

## 1.9.91 - 2026-07-12

- Revalidate notification-loudness outbox routes before dispatch.

## 1.9.90 - 2026-07-12

- Repair inconsistent terminal notification-loudness stop metadata.

## 1.9.89 - 2026-07-12

- Repair malformed activation flags on terminal notification-loudness states.

## 1.9.88 - 2026-07-12

- Fail closed on malformed explicit notification-loudness route statuses.

## 1.9.87 - 2026-07-12

- Fail closed on malformed notification-loudness outbox statuses.

## 1.9.86 - 2026-07-12

- Restrict active notification-loudness outbox items to live statuses.

## 1.9.85 - 2026-07-12

- Normalize notification-loudness system-item tokens case-insensitively.

## 1.9.84 - 2026-07-11

- Recheck current notification-loudness routes inside serialized state updates.

## 1.9.83 - 2026-07-11

- Do not queue notification-loudness prompts for stale identity routes.

## 1.9.82 - 2026-07-11

- Fail closed on inconsistent notification-loudness outbox routes.

## 1.9.81 - 2026-07-11

- Fall back from malformed notification-loudness outbox route keys to valid routes.

## 1.9.80 - 2026-07-11

- Preserve notification-loudness negation precedence without pending state.

## 1.9.79 - 2026-07-11

- Handle mixed-type notification-loudness prompt-window keys safely.

## 1.9.78 - 2026-07-11

- Treat explicit null notification-loudness activation flags as inactive.

## 1.9.77 - 2026-07-11

- Fail closed on malformed legacy notification-loudness cooldown timestamps.

## 1.9.76 - 2026-07-11

- Recognize natural muted notification-loudness replies.

## 1.9.75 - 2026-07-11

- Recognize natural notification-loudness completion and negation phrases.

## 1.9.74 - 2026-07-11

- Reject notification-loudness routes with invalid adapter slots.

## 1.9.73 - 2026-07-11

- Skip adaptive contact timing until a notification-loudness prompt is actually due.

## 1.9.72 - 2026-07-11

- Respect legacy notification-loudness `next_check_at` cooldowns.

## 1.9.71 - 2026-07-11

- Derive legacy notification-loudness outbox route keys from stored routes.

## 1.9.70 - 2026-07-11

- Fail closed on malformed explicit notification-loudness activation flags.

## 1.9.69 - 2026-07-11

- Fail closed when notification-loudness account state storage is unavailable.

## 1.9.68 - 2026-07-11

- Skip non-private routes before evaluating adaptive contact timing.

## 1.9.67 - 2026-07-11

- Let terminal notification-loudness states win over duplicate route-key variants.

## 1.9.66 - 2026-07-11

- Prevent incoming messages from resurrecting inactive notification-loudness checks.

## 1.9.65 - 2026-07-11

- Avoid duplicate notification-loudness prompts while one is dispatching.

## 1.9.64 - 2026-07-11

- Prioritize explicit negations in notification-loudness free-text replies.

## 1.9.63 - 2026-07-11

- Stop notification-loudness queueing when checks are inactive.

## 1.9.62 - 2026-07-11

- Fail closed on malformed notification-loudness state payloads.

## 1.9.61 - 2026-07-11

- Normalize naive notification-loudness timestamps as UTC.

## 1.9.60 - 2026-07-11

- Fail closed on invalid loudness route slots and boolean state values.

## 1.9.59 - 2026-07-11

- Canonicalize proactive dispatch route fields before sending.

## 1.9.58 - 2026-07-11

- Normalize padded IDs in proactive planner and limit helpers.

## 1.9.57 - 2026-07-11

- Normalize padded proactive outbox IDs during worker claims.

## 1.9.56 - 2026-07-11

- Report malformed proactive health payloads instead of crashing.

## 1.9.55 - 2026-07-11

- Fail loudness dispatches visibly when post-claim state cannot be read.

## 1.9.54 - 2026-07-11

- Normalize naive proactive scheduler timestamps as UTC.

## 1.9.53 - 2026-07-11

- Prevent string false values from bypassing proactive contact policies.

## 1.9.52 - 2026-07-11

- Parse persisted proactive boolean values instead of treating false strings as true.

## 1.9.51 - 2026-07-11

- Preserve falsy MCP mappings in runtime policy resolution.

## 1.9.50 - 2026-07-11

- Fail closed when a known MCP tool override has an invalid shape.

## 1.9.49 - 2026-07-11

- Strip control characters from visible status titles.

## 1.9.48 - 2026-07-11

- Make set-valued status labels deterministic without reordering lists.

## 1.9.47 - 2026-07-11

- Preserve valid falsy MCP mappings in status output.

## 1.9.46 - 2026-07-11

- Respect explicit empty environments in proactive status diagnostics.

## 1.9.45 - 2026-07-11

- Report unreadable account directories instead of treating them as empty.

## 1.9.44 - 2026-07-11

- Keep account-memory health diagnostics available when fallback metadata fails.

## 1.9.43 - 2026-07-11

- Keep status output available when a memory backend diagnostic property fails.

## 1.9.42 - 2026-07-11

- Sanitize runtime status counter labels before rendering them.

## 1.9.41 - 2026-07-11

- Report malformed per-tool MCP configurations instead of silently applying
  defaults.

## 1.9.40 - 2026-07-11

- Reject non-finite memory values when estimating JSON payload size.

## 1.9.39 - 2026-07-11

- Handle infinite runtime and identity counters as unknown in status output.

## 1.9.38 - 2026-07-11

- Preserve falsy malformed MCP configurations for status validation.

## 1.9.37 - 2026-07-11

- Reject invalid account-memory backend payload shapes in status size
  diagnostics.

## 1.9.36 - 2026-07-11

- Normalize unknown or malformed Codex-History status tokens before rendering
  machine-readable status lines.

## 1.9.35 - 2026-07-11

- Keep identity status diagnostics alive when the report lacks an instances
  list.

## 1.9.34 - 2026-07-11

- Sanitize the visible status heading before rendering it.

## 1.9.33 - 2026-07-11

- Surface malformed Codex-History backend rows as warnings instead of silently
  dropping them from totals.

## 1.9.32 - 2026-07-11

- Mark skipped or otherwise non-successful Codex-History entries as status
  warnings.

## 1.9.31 - 2026-07-11

- Use one consistent empty-state representation for Codex-History status.

## 1.9.30 - 2026-07-11

- Normalize invalid identity health status tokens to unknown.

## 1.9.29 - 2026-07-11

- Keep null and empty status counters distinguishable from a real numeric zero.

## 1.9.28 - 2026-07-11

- Show malformed runtime and identity counters as unknown instead of zero in
  status diagnostics.

## 1.9.27 - 2026-07-11

- Diagnose malformed MCP status configuration instead of raising during
  status formatting.

## 1.9.26 - 2026-07-11

- Redact secrets and credentials from account-memory health error lines.

## 1.9.25 - 2026-07-11

- Keep status memory-size diagnostics alive when backend data is not JSON
  serializable.

## 1.9.24 - 2026-07-11

- Distinguish unreadable memory files from readable unencrypted files in status
  diagnostics.

## 1.9.23 - 2026-07-11

- Report unavailable memory-file sizes instead of crashing or returning partial
  totals when directory reads fail.

## 1.9.22 - 2026-07-11

- Report unreadable account directories as broken instead of treating them as
  an empty memory store.

## 1.9.21 - 2026-07-11

- Include the memory recovery command when account metadata is broken before
  any account directory exists.

## 1.9.20 - 2026-07-11

- Do not treat invalid explicit account IDs as resolved in status output.

## 1.9.19 - 2026-07-11

- Treat malformed fallback-model configuration as an empty fallback list in
  status output.

## 1.9.18 - 2026-07-11

- Keep status output alive when optional LLM client attributes fail during
  inspection.

## 1.9.17 - 2026-07-11

- Keep identity status diagnostics alive when warning_count contains invalid
  data.

## 1.9.16 - 2026-07-11

- Validate and normalize instance names in Codex-History status diagnostics.

## 1.9.15 - 2026-07-11

- Validate and normalize instance names consistently in identity and secret
  health diagnostics.

## 1.9.14 - 2026-07-11

- Use the validated instance name consistently in account-memory health output.

## 1.9.13 - 2026-07-11

- Reject invalid instance and account identifiers before resolving status
  memory paths.

## 1.9.12 - 2026-07-11

- Do not mask unreadable JSON account memory with its raw file size in
  `/status`.

## 1.9.11 - 2026-07-11

- Keep account-memory health diagnostics alive when fallback status resolution
  fails.

## 1.9.10 - 2026-07-11

- Keep `/status` diagnostic when account-memory backend resolution fails.

## 1.9.9 - 2026-07-11

- Do not report legacy JSON sizes when the configured account-memory backend is
  unavailable or returned partial data.

## 1.9.8 - 2026-07-11

- Reject path-traversal instance names in account-memory health checks.

## 1.9.7 - 2026-07-11

- Fail closed when callback spool delivery responses lack a valid inner
  success object.

## 1.9.6 - 2026-07-11

- Persist generated callback event IDs inside spool payloads so retries retain
  delivery idempotency.

## 1.9.5 - 2026-07-11

- Keep callback spool files when the Dispatcher RPC succeeds transport-wise but
  reports an inner delivery failure.

## 1.9.4 - 2026-07-11

- Accept both `recipient_id` and legacy `account_id` fields when skipping
  already delivered bridge recipients.

## 1.9.3 - 2026-07-11

- Preserve already delivered History-Dispatcher recipients when a bridge claim
  has no remaining open recipient.

## 1.9.2 - 2026-07-11

- Preserve the documented `dispatch-limit 0` semantics across the
  History-Dispatcher bridge so all queued history entries can be queried and
  claimed.

## 1.9.1 - 2026-07-10

- Made scheduling, activity profiles, and notification wake windows use one
  deterministic configurable local timezone (`TEEBOTUS_TIMEZONE`).
- Hardened temporary-file cleanup against symlink replacement races and made
  the first memory-backend fallback warning visible on fresh runtimes.

## 1.9.0 - 2026-07-10

- Added the optional History-Dispatcher bridge and shadow migration path.
- Added the optional full Dispatcher section to the TeeBotus Cinnamon applet.
- Kept the legacy AccountStore readable while Dispatcher claims and receipts
  are exchanged over a bounded owner-only Unix socket.
- Hardened applet snapshot reads, action argv validation, subprocess timeouts,
  generation guards, and removal-time cancellation.
