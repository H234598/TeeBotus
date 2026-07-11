# Changelog

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
